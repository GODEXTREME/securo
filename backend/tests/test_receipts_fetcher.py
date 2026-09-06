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
