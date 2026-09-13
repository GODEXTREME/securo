"""Fetching through a browser.

The protocol plumbing is thin and sits behind `CdpTransport`; what is
worth holding is everything around it — the checks that run before a tab
is opened, the timeout, the tab being closed whatever happens, and the
circuit breaker still speaking for the state.
"""
import asyncio
import json

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
        blank_probes: int = 0,
        interstitial_probes: int = 0,
        never_settles: bool = False,
        tabs: list[tuple[str, str]] | None = None,
    ):
        self.html = html
        self.fail_on = fail_on
        self.hang = hang
        self.error = error
        self.blank_probes = blank_probes
        self.interstitial_probes = interstitial_probes
        self.never_settles = never_settles
        self.probes = 0
        self.opened: list[str] = []
        self.closed: list[str] = []
        #: Tabs the browser already holds, as `(target id, url)` — what a
        #: previous attempt left behind.
        self.tabs: list[tuple[str, str]] = list(tabs or [])

    async def open_tab(self, url: str) -> str:
        if self.fail_on == "open":
            raise self.error or RuntimeError("no browser there")
        if self.hang:
            await asyncio.sleep(60)
        self.opened.append(url)
        return "tab-1"

    async def evaluate(self, target_id: str, expression: str):
        if "readyState" in expression:
            self.probes += 1
            if self.probes <= self.blank_probes:
                # A tab that has not navigated yet: its own empty
                # document, which reports `complete` all the same.
                return json.dumps({"url": "about:blank", "state": "complete", "body": 0})
            if self.probes <= self.blank_probes + self.interstitial_probes:
                # A real page, with real content, that is about to
                # replace itself — Rio de Janeiro's browser check.
                return json.dumps({"url": "https://portal/tspd", "state": "complete", "body": 80})
            if self.never_settles:
                # A challenge widget redrawing itself: a real page, never
                # twice the same, for as long as nobody clicks it.
                return json.dumps(
                    {"url": "https://portal/x", "state": "complete", "body": 100 + self.probes}
                )
            return json.dumps({"url": "https://portal/x", "state": "complete", "body": 120})
        if self.fail_on == "html":
            raise RuntimeError("the tab returned no HTML")
        return self.html

    async def close_tab(self, target_id: str) -> None:
        if self.fail_on == "close":
            raise RuntimeError("already gone")
        self.closed.append(target_id)

    async def list_tabs(self) -> list[tuple[str, str]]:
        if self.fail_on == "list":
            raise RuntimeError("this browser does not list")
        return list(self.tabs)


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
    # No interval here: this is about what two *attempts* do to the
    # circuit, and a fetch the rate limiter turns away never reaches the
    # portal, so it rightly counts as nothing.
    broken = BrowserFetcher(
        transport=FakeCdp(fail_on="open"), gate=gate, settle_seconds=0,
        min_interval_ms=0, circuit_failures=2,
    )
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


@pytest.mark.asyncio
async def test_an_empty_tab_is_not_a_page():
    """`PUT /json/new` returns before the navigation does, and a tab that
    has not navigated reports `complete` for its own empty document. A
    deployment read that and stored
    `<html><head></head><body></body></html>` as the portal's answer."""
    cdp = FakeCdp(blank_probes=3)
    result = await _fetcher(cdp).fetch(URL, HOSTS, "RJ")

    assert result.outcome == "page"
    assert result.page is not None and "tabResult" in result.page.html
    assert cdp.probes > 3, "the tab was asked again instead of read once"


@pytest.mark.asyncio
async def test_a_page_that_replaces_itself_is_not_read_first():
    """Rio de Janeiro's browser check is a real page with real content:
    waiting for *a* document would read it and call the note blocked. It
    is read only once the tab holds the same thing twice."""
    cdp = FakeCdp(blank_probes=1, interstitial_probes=2)
    result = await _fetcher(cdp).fetch(URL, HOSTS, "RJ")

    assert result.outcome == "page"
    assert result.page is not None and "tabResult" in result.page.html


@pytest.mark.asyncio
async def test_the_browser_spends_the_same_token_as_a_plain_fetch():
    """A browser loads the whole page, so it is a heavier client than a
    request, not a lighter one. Re-importing a backlog must not arrive as
    fast as Chrome can open tabs."""
    gate = MemoryGate()
    cdp = FakeCdp()
    fetcher = BrowserFetcher(transport=cdp, gate=gate, settle_seconds=0, min_interval_ms=60_000)

    first = await fetcher.fetch(URL, HOSTS, "RJ")
    second = await fetcher.fetch(URL, HOSTS, "RJ")

    assert first.outcome == "page"
    assert second.outcome == "rate_limited"
    assert cdp.opened == [URL], "the second fetch never opened a tab"


CHALLENGE = '<html><body><div class="cf-turnstile" data-sitekey="x"></div></body></html>'


@pytest.mark.asyncio
async def test_a_page_that_never_settles_comes_back_with_the_timeout():
    """The commonest reason a portal never settles is that it is showing a
    challenge, and a challenge is something the caller can recognise. The
    outcome stays `timeout` — this is evidence, not an answer."""
    cdp = FakeCdp(html=CHALLENGE, never_settles=True)
    result = await _fetcher(cdp, timeout_seconds=0.2).fetch(URL, HOSTS, "RJ")

    assert result.outcome == "timeout"
    assert result.page is not None
    assert "cf-turnstile" in result.page.html
    assert result.page.url == URL
    # Housekeeping still happens: the tab does not outlive the attempt.
    assert cdp.closed == ["tab-1"]


@pytest.mark.asyncio
async def test_a_browser_that_never_opened_the_tab_has_no_page_to_offer():
    """`hang` stops before a tab exists, so there is nothing to read and
    the timeout carries nothing rather than inventing an empty page."""
    result = await _fetcher(FakeCdp(hang=True), timeout_seconds=0.05).fetch(URL, HOSTS, "RJ")

    assert result.outcome == "timeout"
    assert result.page is None


@pytest.mark.asyncio
async def test_reading_the_unsettled_page_may_fail_without_changing_the_outcome():
    """The browser had already stopped answering; asking it one more
    question must not turn a timeout into a crash."""
    cdp = FakeCdp(never_settles=True, fail_on="html")
    result = await _fetcher(cdp, timeout_seconds=0.2).fetch(URL, HOSTS, "RJ")

    assert result.outcome == "timeout"
    assert result.page is None


def _challenge(page) -> bool:
    return "cf-turnstile" in page.html


@pytest.mark.asyncio
async def test_a_challenge_is_left_on_screen_for_someone_to_pass():
    """The one page worth not closing. Somebody can act on it, and the
    next attempt reads the same tab — so this is a tab handed over, not a
    tab abandoned."""
    cdp = FakeCdp(html=CHALLENGE, never_settles=True)
    result = await _fetcher(cdp, timeout_seconds=0.2).fetch(
        URL, HOSTS, "ES", keep_open=_challenge
    )

    assert result.outcome == "timeout"
    assert cdp.closed == [], "the tab stays"
    assert result.detail == "browser is waiting for you"
    assert result.kept_open, "the caller has to know there is something on screen to point at"


@pytest.mark.asyncio
async def test_anything_else_that_will_not_settle_is_still_closed():
    """Nobody is coming to look at a page that is merely slow, and a tab
    left open keeps running scripts."""
    cdp = FakeCdp(html=NOTE, never_settles=True)
    result = await _fetcher(cdp, timeout_seconds=0.2).fetch(
        URL, HOSTS, "ES", keep_open=_challenge
    )

    assert result.outcome == "timeout"
    assert cdp.closed == ["tab-1"]
    assert not result.kept_open, "nothing was left behind, so nothing to send anyone to"


@pytest.mark.asyncio
async def test_the_next_attempt_reads_the_tab_that_was_left():
    """Where the whole arrangement pays off: the person passed the check
    in that tab, so it now holds the note. Opening a fresh one would work
    too — the cookie is in the profile — but reading theirs is the
    direct answer, and it is what closes the loop."""
    cdp = FakeCdp(tabs=[("tab-left", URL)])

    result = await _fetcher(cdp).fetch(URL, HOSTS, "ES")

    assert result.outcome == "page"
    assert cdp.opened == [], "no second tab beside the one already there"
    assert cdp.closed == ["tab-left"], "and it is cleaned up once read"


@pytest.mark.asyncio
async def test_a_tab_left_on_another_page_is_not_mistaken_for_ours():
    """Matching is on the URL. Anything else open in that browser — a
    different note, somebody's own browsing — is none of this fetch's
    business."""
    cdp = FakeCdp(tabs=[("tab-other", "https://example.invalid/somewhere")])

    result = await _fetcher(cdp).fetch(URL, HOSTS, "ES")

    assert result.outcome == "page"
    assert cdp.opened == [URL], "a tab of our own was opened"


@pytest.mark.asyncio
async def test_a_tab_showing_somebody_else_s_note_is_not_taken():
    """Where one URL serves a whole state — Espírito Santo's form — the
    address stops telling two receipts apart, and the tab a person filled
    in holds exactly one of them. Taking it for the other would read the
    wrong note, which is terminal: `key_mismatch` stops that receipt
    until somebody retries it by hand."""
    cdp = FakeCdp(html=NOTE, tabs=[("tab-theirs", URL)])

    result = await _fetcher(cdp).fetch(
        URL, HOSTS, "ES", claimable=lambda page: "mine" in page.html
    )

    assert result.outcome == "page"
    assert cdp.opened == [URL], "a tab of our own, beside theirs"
    assert "tab-theirs" not in cdp.closed, "and theirs is left exactly as it was"


@pytest.mark.asyncio
async def test_a_tab_showing_our_own_note_is_taken():
    """The other half: the person passed the check and searched for *this*
    note, so this is the tab the whole arrangement exists to read."""
    cdp = FakeCdp(html="<html>mine</html>", tabs=[("tab-ours", URL)])

    result = await _fetcher(cdp).fetch(
        URL, HOSTS, "ES", claimable=lambda page: "mine" in page.html
    )

    assert result.outcome == "page"
    assert cdp.opened == [], "no second tab"
    assert cdp.closed == ["tab-ours"]


@pytest.mark.asyncio
async def test_a_tab_that_cannot_be_read_is_left_alone():
    """Claiming means reading, and a tab that answers nothing cannot be
    identified. A spare tab costs a little memory; reading a page nobody
    has identified costs a receipt."""
    cdp = FakeCdp(fail_on="html", tabs=[("tab-silent", URL)])

    result = await _fetcher(cdp, timeout_seconds=1).fetch(
        URL, HOSTS, "ES", claimable=lambda page: True
    )

    assert cdp.opened == [URL], "ours was opened rather than theirs taken"
    assert "tab-silent" not in cdp.closed, "and the unreadable one is left where it was"
    assert result.outcome == "portal_down", "this browser answers nothing at all"


@pytest.mark.asyncio
async def test_without_a_question_to_ask_the_url_is_enough():
    """No `claimable` means no way to tell two receipts apart, which is
    every state but one: there the URL carries the key and a tab on it is
    unambiguous."""
    cdp = FakeCdp(tabs=[("tab-left", URL)])

    result = await _fetcher(cdp).fetch(URL, HOSTS, "RJ")

    assert result.outcome == "page"
    assert cdp.opened == [] and cdp.closed == ["tab-left"]


@pytest.mark.asyncio
async def test_a_browser_that_cannot_list_its_tabs_still_works():
    """`/json/list` is the newest thing asked of the browser. If it is not
    there, the fetch opens a tab as it always did rather than failing."""
    cdp = FakeCdp(fail_on="list")

    result = await _fetcher(cdp).fetch(URL, HOSTS, "ES")

    assert result.outcome == "page"
    assert cdp.opened == [URL]
