"""Fetching through a browser.

The protocol plumbing is thin and sits behind `CdpTransport`; what is
worth holding is everything around it — the checks that run before a tab
is opened, the timeout, the tab being closed whatever happens, and the
circuit breaker still speaking for the state.
"""
import asyncio

import pytest

from app.receipts.browser import BrowserFetcher
from app.receipts.fetcher import MemoryGate

HOSTS = frozenset({"consultadfe.fazenda.rj.gov.br"})
URL = "https://consultadfe.fazenda.rj.gov.br/consultaNFCe/QRCode?p=x"
NOTE = '<html><body><table id="tabResult"></table></body></html>'


class FakeCdp:
    """A browser that answers instantly and remembers what it was asked."""

    def __init__(self, html: str = NOTE, *, fail_on: str | None = None, hang: bool = False):
        self.html = html
        self.fail_on = fail_on
        self.hang = hang
        self.opened: list[str] = []
        self.closed: list[str] = []

    async def open_tab(self, url: str) -> str:
        if self.fail_on == "open":
            raise RuntimeError("no browser there")
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
