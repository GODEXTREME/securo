"""The fetcher: allowlist, private-address refusal, redirects, rate limit
and circuit breaker — all with a mock transport, no network."""
from typing import Callable

import httpx
import pytest

from app.receipts.fetcher import Fetcher, MemoryGate, Resolver, host_allowed

HOSTS = frozenset({"app.sefaz.es.gov.br"})
URL = "http://app.sefaz.es.gov.br/ConsultaNFCe?p=x"


async def _public(host: str) -> bool:
    return False


async def _private(host: str) -> bool:
    return True


def _fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    min_interval_ms: int = 0,
    circuit_failures: int = 3,
    resolver: Resolver = _public,
) -> Fetcher:
    return Fetcher(
        MemoryGate(),
        transport=httpx.MockTransport(handler),
        min_interval_ms=min_interval_ms,
        circuit_failures=circuit_failures,
        circuit_open_seconds=60,
        resolver=resolver,
    )


class TestHostAllowed:
    @pytest.mark.parametrize(
        "url,ok",
        [
            (URL, True),
            ("https://APP.sefaz.es.gov.br/x", True),
            ("http://evil.example/ConsultaNFCe", False),
            ("ftp://app.sefaz.es.gov.br/x", False),
            ("http://app.sefaz.es.gov.br.evil.example/x", False),
            ("not a url", False),
        ],
    )
    def test(self, url, ok):
        assert host_allowed(url, HOSTS) is ok


@pytest.mark.asyncio
async def test_happy_path_returns_the_page():
    fetcher = _fetcher(lambda req: httpx.Response(200, text="<html>ok</html>"))
    result = await fetcher.fetch(URL, HOSTS, "ES")
    assert result.outcome == "page" and result.page is not None
    assert result.page.html == "<html>ok</html>" and result.page.status_code == 200


@pytest.mark.asyncio
async def test_disallowed_host_never_hits_the_transport():
    calls = []
    fetcher = _fetcher(lambda req: calls.append(req) or httpx.Response(200))
    result = await fetcher.fetch("http://evil.example/x", HOSTS, "ES")
    assert result.outcome == "blocked" and calls == []


@pytest.mark.asyncio
async def test_private_address_is_refused():
    calls = []
    fetcher = _fetcher(lambda req: calls.append(req) or httpx.Response(200), resolver=_private)
    result = await fetcher.fetch(URL, HOSTS, "ES")
    assert result.outcome == "blocked" and "private" in (result.detail or "") and calls == []


@pytest.mark.asyncio
async def test_redirect_within_allowlist_is_followed_once():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/ConsultaNFCe":
            return httpx.Response(302, headers={"location": "/ConsultaNFCe/danfe"})
        return httpx.Response(200, text="danfe")

    result = await _fetcher(handler).fetch(URL, HOSTS, "ES")
    assert result.outcome == "page" and result.page is not None and result.page.html == "danfe"
    assert result.page.url.endswith("/ConsultaNFCe/danfe")


@pytest.mark.asyncio
async def test_redirect_off_allowlist_is_blocked():
    handler = lambda req: httpx.Response(302, headers={"location": "http://evil.example/steal"})  # noqa: E731
    result = await _fetcher(handler).fetch(URL, HOSTS, "ES")
    assert result.outcome == "blocked" and "disallowed" in (result.detail or "")


@pytest.mark.asyncio
async def test_rate_limit_between_calls_to_one_host():
    fetcher = _fetcher(lambda req: httpx.Response(200, text="ok"), min_interval_ms=60_000)
    assert (await fetcher.fetch(URL, HOSTS, "ES")).outcome == "page"
    assert (await fetcher.fetch(URL, HOSTS, "ES")).outcome == "rate_limited"


@pytest.mark.asyncio
async def test_circuit_opens_after_consecutive_failures():
    calls = []
    fetcher = _fetcher(lambda req: calls.append(req) or httpx.Response(503), circuit_failures=3)
    for _ in range(3):
        assert (await fetcher.fetch(URL, HOSTS, "ES")).outcome == "portal_down"
    result = await fetcher.fetch(URL, HOSTS, "ES")
    assert result.outcome == "portal_down" and "circuit open" in (result.detail or "")
    assert len(calls) == 3, "an open circuit sends nothing"


@pytest.mark.asyncio
async def test_success_resets_the_failure_count():
    state = {"fail": True}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503) if state["fail"] else httpx.Response(200, text="ok")

    fetcher = _fetcher(handler, circuit_failures=3)
    await fetcher.fetch(URL, HOSTS, "ES")
    await fetcher.fetch(URL, HOSTS, "ES")
    state["fail"] = False
    assert (await fetcher.fetch(URL, HOSTS, "ES")).outcome == "page"
    state["fail"] = True
    for _ in range(2):
        await fetcher.fetch(URL, HOSTS, "ES")
    # Two failures after a success: still under the threshold of three.
    result = await fetcher.fetch(URL, HOSTS, "ES")
    assert "circuit open" not in (result.detail or "")


@pytest.mark.asyncio
async def test_429_is_rate_limited_and_4xx_is_http_error():
    assert (await _fetcher(lambda req: httpx.Response(429)).fetch(URL, HOSTS, "ES")).outcome == "rate_limited"
    assert (await _fetcher(lambda req: httpx.Response(404)).fetch(URL, HOSTS, "ES")).outcome == "http_error"


@pytest.mark.asyncio
async def test_timeout_counts_as_a_failure():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    result = await _fetcher(handler).fetch(URL, HOSTS, "ES")
    assert result.outcome == "timeout"


@pytest.mark.asyncio
async def test_a_redirect_does_not_spend_a_second_rate_limit_token():
    """Regression: the ES portal answers http→https with a redirect. The
    interval is per fetch, not per hop — counting the hop as a second
    request made every real fetch come back `rate_limited` and the receipt
    retry every 30 s forever."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.scheme == "http":
            return httpx.Response(301, headers={"location": str(req.url.copy_with(scheme="https"))})
        return httpx.Response(200, text="danfe")

    result = await _fetcher(handler, min_interval_ms=60_000).fetch(URL, HOSTS, "ES")
    assert result.outcome == "page" and result.page is not None and result.page.html == "danfe"


@pytest.mark.asyncio
async def test_the_user_agent_names_us_inside_a_browser_envelope():
    """Rio de Janeiro refuses anything that does not look like a browser —
    `Securo/receipts` and the conventional `(compatible; …)` form both got
    a block page. The envelope is what gets through; the name and the link
    ride at the end so the request still says who is making it."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, text="<html>ok</html>")

    fetcher = Fetcher(MemoryGate(), min_interval_ms=0, transport=httpx.MockTransport(handler), resolver=_public)
    await fetcher.fetch("https://app.sefaz.es.gov.br/x", frozenset({"app.sefaz.es.gov.br"}), "ES")

    assert len(seen) == 1
    assert seen[0].startswith("Mozilla/5.0 ")
    assert "Securo/1.0" in seen[0] and "github.com/godextreme/securo" in seen[0]


def test_the_configured_user_agent_is_the_fetchers_own():
    """These were two separate strings, and the setting silently won: the
    constant was corrected and every request kept sending the old value,
    because the worker passes the setting in. One source of truth now, and
    this is what holds it."""
    from app.core.config import get_settings
    from app.receipts.fetcher import DEFAULT_USER_AGENT

    assert get_settings().receipts_user_agent == DEFAULT_USER_AGENT


class TestFollowUp:
    """A second request on the first one's client. Goiás needs it: the
    barcode is on a page that only answers a client the portal has just
    served, so the session is the credential."""

    GO = frozenset({"nfeweb.sefaz.go.gov.br"})
    FIRST = "https://nfeweb.sefaz.go.gov.br/nfeweb/sites/nfce/danfeNFCe?p=x"
    SECOND = "https://nfeweb.sefaz.go.gov.br/nfeweb/sites/nfce/render/NFCe?chNFe=y"

    @pytest.mark.asyncio
    async def test_the_second_page_is_what_comes_back(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if "render" in str(request.url):
                return httpx.Response(200, text="<html>detalhada</html>")
            return httpx.Response(200, text="<html>danfe</html>", headers={"set-cookie": "s=1; Path=/"})

        result = await _fetcher(handler).fetch(
            self.FIRST, self.GO, "GO", follow=lambda page: self.SECOND
        )

        assert result.outcome == "page"
        assert result.page is not None
        assert result.page.html == "<html>detalhada</html>"
        assert result.page.url == self.SECOND
        assert seen == [self.FIRST, self.SECOND]

    @pytest.mark.asyncio
    async def test_the_session_is_carried(self):
        """The whole reason this is one call and not two: the cookie the
        first response set has to be on the second request."""
        cookies: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            cookies.append(request.headers.get("cookie", ""))
            if "render" in str(request.url):
                return httpx.Response(200, text="ok")
            return httpx.Response(200, text="danfe", headers={"set-cookie": "JSESSIONID=abc; Path=/"})

        await _fetcher(handler).fetch(self.FIRST, self.GO, "GO", follow=lambda page: self.SECOND)

        assert cookies[0] == ""
        assert "JSESSIONID=abc" in cookies[1]

    @pytest.mark.asyncio
    async def test_a_follow_up_off_the_allowlist_is_refused(self):
        """The URL is built from a page the portal wrote, so it is user
        input by another name and gets the same check the first one did."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="danfe")

        result = await _fetcher(handler).fetch(
            self.FIRST, self.GO, "GO", follow=lambda page: "https://evil.example.com/x"
        )

        assert result.outcome == "blocked" and "follow-up host" in (result.detail or "")

    @pytest.mark.asyncio
    async def test_a_follow_up_that_fails_keeps_the_note(self):
        """The receipt did arrive; only the richer view did not. Losing
        the first page over that would be worse than reading it."""
        def handler(request: httpx.Request) -> httpx.Response:
            if "render" in str(request.url):
                return httpx.Response(403, text="nope")
            return httpx.Response(200, text="<html>danfe</html>")

        result = await _fetcher(handler).fetch(
            self.FIRST, self.GO, "GO", follow=lambda page: self.SECOND
        )

        assert result.outcome == "page"
        assert result.page is not None and result.page.html == "<html>danfe</html>"

    @pytest.mark.asyncio
    async def test_no_follow_up_means_one_request(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, text="danfe")

        await _fetcher(handler).fetch(self.FIRST, self.GO, "GO", follow=lambda page: None)

        assert seen == [self.FIRST]
