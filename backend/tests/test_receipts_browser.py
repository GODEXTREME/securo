"""Fetching through a browser.

The protocol plumbing is thin and sits behind `CdpTransport`; what is
worth holding is everything around it — the checks that run before a tab
is opened, the timeout, the tab being closed whatever happens, and the
circuit breaker still speaking for the state.
"""
import asyncio

import httpx
import pytest

from app.receipts.browser import BrowserFetcher, HttpWsCdp
from app.receipts.fetcher import MemoryGate

HOSTS = frozenset({"consultadfe.fazenda.rj.gov.br"})
URL = "https://consultadfe.fazenda.rj.gov.br/consultaNFCe/QRCode?p=x"
NOTE = '<html><body><table id="tabResult"></table></body></html>'


class FakeCdp:
    """A browser that answers instantly and remembers what it was asked."""

    endpoint = "http://kasm-chrome:9222"

    def __init__(
        self,
        html: str = NOTE,
        *,
        fail_on: str | None = None,
        hang: bool = False,
        error: Exception | None = None,
    ):
        self.html = html
        self.fail_on = fail_on
        self.hang = hang
        self.error = error
        self.opened: list[str] = []
        self.closed: list[str] = []

    async def open_tab(self, url: str) -> str:
        if self.fail_on == "open":
            raise self.error or RuntimeError("no browser there")
        if self.hang:
            await asyncio.sleep(60)
        self.opened.append(url)
        return "tab-1"

    async def outer_html(self, target_id: str) -> str:
        if self.fail_on == "html":
            raise RuntimeError("the tab returned no HTML")
        return self.html

    async def close_tab(self, target_id: str) -> None:
        if self.fail_on == "close":
            raise RuntimeError("already gone")
        self.closed.append(target_id)


def _fetcher(cdp: FakeCdp, **kwargs) -> BrowserFetcher:
    return BrowserFetcher(transport=cdp, gate=MemoryGate(), settle_seconds=0, **kwargs)


@pytest.mark.asyncio
async def test_brings_the_page_back_and_closes_the_tab():
    cdp = FakeCdp()
    result = await _fetcher(cdp).fetch(URL, HOSTS, "RJ")

    assert result.outcome == "page"
    assert result.page is not None and "tabResult" in result.page.html
    assert cdp.opened == [URL]
    assert cdp.closed == ["tab-1"], "a tab left open keeps running scripts"


@pytest.mark.asyncio
async def test_a_host_outside_the_allowlist_never_reaches_the_browser():
    """The URL comes from a QR code. A browser follows redirects and runs
    scripts, so the check that mattered for a plain request matters more
    here — and it has to happen before the tab exists."""
    cdp = FakeCdp()
    result = await _fetcher(cdp).fetch("https://evil.example.com/x", HOSTS, "RJ")

    assert result.outcome == "blocked"
    assert cdp.opened == []


@pytest.mark.asyncio
async def test_an_open_circuit_is_respected():
    cdp = FakeCdp()
    gate = MemoryGate()
    for _ in range(5):
        await gate.record_failure("RJ", 5, 900)
    fetcher = BrowserFetcher(transport=cdp, gate=gate, settle_seconds=0)

    result = await fetcher.fetch(URL, HOSTS, "RJ")
    assert result.outcome == "portal_down"
    assert cdp.opened == []


@pytest.mark.asyncio
async def test_a_browser_that_does_not_answer_is_a_timeout():
    cdp = FakeCdp(hang=True)
    result = await _fetcher(cdp, timeout_seconds=0.05).fetch(URL, HOSTS, "RJ")
    assert result.outcome == "timeout"


@pytest.mark.asyncio
async def test_a_browser_that_is_not_there_is_the_portal_being_down():
    """From the state machine's side it is the same thing: nothing came
    back, try later. The detail says which, for a person reading it."""
    result = await _fetcher(FakeCdp(fail_on="open")).fetch(URL, HOSTS, "RJ")
    assert result.outcome == "portal_down"
    assert "browser error" in (result.detail or "")


@pytest.mark.asyncio
async def test_a_tab_that_will_not_close_does_not_lose_the_page():
    """Closing is housekeeping. Failing it must not throw away a note the
    browser already handed over."""
    result = await _fetcher(FakeCdp(fail_on="close")).fetch(URL, HOSTS, "RJ")
    assert result.outcome == "page"


@pytest.mark.asyncio
async def test_failures_count_towards_the_circuit_and_success_clears_it():
    gate = MemoryGate()
    broken = BrowserFetcher(transport=FakeCdp(fail_on="open"), gate=gate, settle_seconds=0, circuit_failures=2)
    await broken.fetch(URL, HOSTS, "RJ")
    await broken.fetch(URL, HOSTS, "RJ")
    assert await gate.circuit_open("RJ")

    fresh = MemoryGate()
    await fresh.record_failure("RJ", 5, 900)
    working = BrowserFetcher(transport=FakeCdp(), gate=fresh, settle_seconds=0)
    assert (await working.fetch(URL, HOSTS, "RJ")).outcome == "page"
    assert not await fresh.circuit_open("RJ")


class TestWhichFetcher:
    """Configuration decides, and the default decides nothing."""

    def test_no_configuration_means_no_browser(self):
        from app.tasks.receipt_tasks import browser_ufs

        assert browser_ufs("") == frozenset()

    def test_states_are_read_as_a_list(self):
        from app.tasks.receipt_tasks import browser_ufs

        assert browser_ufs("es, RJ ") == frozenset({"ES", "RJ"})


@pytest.mark.asyncio
async def test_an_unreachable_browser_is_not_the_state_s_fault():
    """`All connection attempts failed` means the portal was never asked.
    Closing the circuit on that would lock the state out of the HTTP
    fetcher, which shares the gate and works — so it stays open, and the
    message names the address that did not answer."""
    gate = MemoryGate()
    cdp = FakeCdp(fail_on="open", error=httpx.ConnectError("All connection attempts failed"))
    fetcher = BrowserFetcher(transport=cdp, gate=gate, settle_seconds=0, circuit_failures=1)

    result = await fetcher.fetch(URL, HOSTS, "RJ")

    assert result.outcome == "portal_down"
    assert "http://kasm-chrome:9222" in (result.detail or "")
    assert not await gate.circuit_open("RJ"), "the browser being down is not the portal being down"


@pytest.mark.asyncio
async def test_a_browser_that_answers_badly_still_counts_against_the_state():
    """A reached browser that fails mid-fetch is the ordinary failure the
    circuit exists for."""
    gate = MemoryGate()
    cdp = FakeCdp(fail_on="html")
    fetcher = BrowserFetcher(transport=cdp, gate=gate, settle_seconds=0, circuit_failures=1)

    result = await fetcher.fetch(URL, HOSTS, "RJ")

    assert result.outcome == "portal_down"
    assert await gate.circuit_open("RJ")


def test_the_socket_goes_to_us_and_the_url_stays_chrome_s():
    """Chrome echoes the Host it was given, so the URL it reports says
    `localhost` — the one name the upgrade must carry, and an address
    that reaches nothing from here. The destination is ours; the URL is
    not."""
    assert HttpWsCdp("http://kasm-chrome:9223")._ws_target() == ("kasm-chrome", 9223)


def test_a_url_without_a_port_gets_the_scheme_s_own():
    assert HttpWsCdp("http://chrome")._ws_target() == ("chrome", 80)
    assert HttpWsCdp("https://chrome")._ws_target() == ("chrome", 443)


def test_chrome_is_told_a_host_it_accepts():
    """Chrome refuses a DevTools request whose Host is not localhost or
    an IP — which is every request that arrives through a forwarder."""
    assert HttpWsCdp("http://kasm-chrome:9223")._client().headers["host"] == "localhost"
