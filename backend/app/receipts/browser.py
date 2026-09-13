"""Fetching a note through a real browser.

Both supported portals refuse a plain request and answer a browser: the
Espírito Santo one with a Cloudflare challenge, the Rio de Janeiro one
with an F5 script that computes a cookie in JavaScript. A browser
running on the same network reaches the note in both cases — that is
observed, not assumed.

So this drives one. The browser is the operator's own (a Kasm Chrome
container is what this was written against), reached over the Chrome
DevTools Protocol: open a tab, wait for the page, take its HTML, close
the tab. Nothing here defeats a challenge; a challenge that wants a
person is still answered by a person, in that browser, and the cookie
their click leaves in the profile is what the next fetch reuses.

The protocol work is deliberately thin and sits behind `CdpTransport`,
so what this module is actually responsible for — the safety checks
before navigating, the timeout, and turning a page into a `FetchResult`
— can be tested without a browser.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.receipts.adapters.base import FetchedPage
from app.receipts.fetcher import FetchResult, FollowUp, Gate, host_allowed

#: How long to spend reading a page that never settled. Short on purpose:
#: the caller's budget is already spent by the time this runs.
UNSETTLED_READ_SECONDS = 5.0

#: How long to let a loaded page settle before reading it. The portals'
#: own scripts run in well under a second; this is slack for a cold
#: browser, and it is *added to* waiting for the document, never
#: instead of it.
SETTLE_SECONDS = 3.0

#: How often to ask the tab whether it has a document yet.
POLL_SECONDS = 0.5

#: What the tab holds: enough to tell an empty tab from a page, and one
#: page from the next. A tab that has not navigated reports `complete`
#: for its own empty document — which is how a fetch came back as
#: `<html><head></head><body></body></html>` — so the URL and the body
#: are looked at too, and their changing is how a reload is noticed.
_READY_PROBE = (
    "JSON.stringify({"
    "url: location.href,"
    "state: document.readyState,"
    "body: document.body ? document.body.innerHTML.length : 0"
    "})"
)


class CdpTransport(Protocol):
    """The four things this needs from a browser. Implemented over HTTP
    and a WebSocket below; replaced wholesale in tests."""

    #: Where this transport expects the browser to be. Only ever used in
    #: an error message — and it is the one fact that message needs, since
    #: the first thing that goes wrong is pointing at the wrong address.
    endpoint: str

    async def open_tab(self, url: str) -> str:
        """Navigate a new tab to `url`. Returns its target id."""

    async def evaluate(self, target_id: str, expression: str) -> Any:
        """Run an expression in the tab and return its value."""

    async def close_tab(self, target_id: str) -> None:
        ...

    async def list_tabs(self) -> list[tuple[str, str]]:
        """Every open page, as `(target id, url)`."""


#: Whether a page that never settled is worth leaving on screen for a
#: person to act on. The caller answers, because only it knows the state's
#: adapter and therefore what a refusal looks like there.
KeepOpen = Callable[[FetchedPage], bool]


@dataclass
class BrowserFetcher:
    """Same shape as `Fetcher`, a browser underneath.

    The safety the HTTP fetcher provides is not weakened by going through
    a browser — if anything it matters more, since a browser follows
    redirects and runs scripts. The host allowlist is checked before the
    tab is opened, and the circuit breaker still speaks for the state.
    """

    transport: CdpTransport
    gate: Gate
    timeout_seconds: float = 30.0
    settle_seconds: float = SETTLE_SECONDS
    min_interval_ms: int = 2000
    circuit_failures: int = 5
    circuit_open_seconds: int = 900

    async def _follow(
        self, html: str, url: str, follow: FollowUp, allowed_hosts: frozenset[str]
    ) -> tuple[str, str]:
        """The second page, in a second tab.

        A browser keeps its cookies per profile, not per tab, so the
        session the first page established is already there — no state
        has to be carried across by hand. The allowlist is checked again
        because the URL was built from a page the portal wrote.
        """
        page = FetchedPage(url=url, status_code=200, html=html, fetched_at=datetime.now(timezone.utc))
        target = follow(page)
        if not target or not host_allowed(target, allowed_hosts):
            return html, url
        second: Optional[str] = None
        try:
            second = await self.transport.open_tab(target)
            return await self._settled_html(second), target
        finally:
            if second is not None:
                try:
                    await self.transport.close_tab(second)
                except Exception:  # noqa: BLE001
                    pass

    async def _settled_html(self, target_id: str) -> str:
        """The document, once it has stopped changing.

        Opening a tab returns before the navigation does, so a fixed
        sleep reads whatever happens to be there — for a portal that
        redirects and then rewrites itself, that is an empty document.
        Waiting for *a* document is not enough either: Rio de Janeiro's
        interstitial is a real page with real content, and it replaces
        itself once its script has computed a cookie.

        So what is waited for is stillness. The tab is asked what it
        holds; a settle later it is asked again; when the two answers
        agree, that is the page. The caller's timeout bounds the wait,
        and a portal that never settles times out rather than returning
        half a page.
        """
        previous: Optional[tuple[str, int]] = None
        while True:
            current = await self._probe(target_id)
            if current is not None and current == previous:
                break
            previous = current
            await asyncio.sleep(self.settle_seconds if current else POLL_SECONDS)
        html = await self.transport.evaluate(target_id, "document.documentElement.outerHTML")
        if not isinstance(html, str):
            raise RuntimeError("the tab returned no HTML")
        return html

    async def _best_effort_html(self, target_id: Optional[str]) -> Optional[str]:
        """Whatever the tab holds, or nothing.

        Called only when the wait has already failed, so it cannot be
        allowed to fail again: a browser that has stopped answering is
        exactly the case this runs in. Its own short budget keeps a hung
        tab from doubling the time the caller already spent.
        """
        if target_id is None:
            return None
        try:
            async with asyncio.timeout(UNSETTLED_READ_SECONDS):
                html = await self.transport.evaluate(target_id, "document.documentElement.outerHTML")
        except Exception:  # noqa: BLE001 — best effort, by definition
            return None
        return html if isinstance(html, str) and html.strip() else None

    async def _probe(self, target_id: str) -> Optional[tuple[str, int]]:
        """What the tab holds right now, or None while it holds nothing."""
        raw = await self.transport.evaluate(target_id, _READY_PROBE)
        if not isinstance(raw, str):
            return None
        probe = json.loads(raw)
        url, state, body = probe.get("url"), probe.get("state"), int(probe.get("body") or 0)
        if state != "complete" or url in (None, "", "about:blank") or body == 0:
            return None
        return str(url), body

    async def _claim_tab(self, url: str) -> str:
        """The tab for this URL: the one a previous attempt left open, or
        a new one.

        A tab is only ever left behind when the page was a challenge and
        somebody might act on it. Finding it again is the whole point —
        it is where that person passed the check, and it now holds the
        note. Anything left on *another* portal URL is a leftover nobody
        is coming back to, and is closed.

        """
        try:
            tabs = await self.transport.list_tabs()
        except Exception:  # noqa: BLE001 — an older browser may not list
            tabs = []
        for target_id, open_url in tabs:
            if open_url == url:
                return target_id
        return await self.transport.open_tab(url)

    async def fetch(
        self,
        url: str,
        allowed_hosts: frozenset[str],
        uf: str,
        *,
        follow: FollowUp | None = None,
        keep_open: KeepOpen | None = None,
    ) -> FetchResult:
        if not host_allowed(url, allowed_hosts):
            return FetchResult("blocked", detail=f"host not allowed for {uf}: {url}")
        if await self.gate.circuit_open(uf):
            return FetchResult("portal_down", detail=f"circuit open for {uf}")

        # The same token the HTTP fetcher spends, from the same bucket. A
        # browser is a heavier client than a plain request, not a lighter
        # one — it loads the whole page — so the portal's interval applies
        # at least as much. Without this a batch of retries arrives as
        # fast as Chrome can open tabs.
        host = urlsplit(url).hostname or ""
        if not await self.gate.acquire(host, self.min_interval_ms):
            return FetchResult("rate_limited", detail=f"interval not elapsed for {host}")

        target_id: Optional[str] = None
        keep = False
        try:
            async with asyncio.timeout(self.timeout_seconds):
                target_id = await self._claim_tab(url)
                html = await self._settled_html(target_id)
                if follow is not None:
                    html, url = await self._follow(html, url, follow, allowed_hosts)
        except asyncio.TimeoutError:
            await self.gate.record_failure(uf, self.circuit_failures, self.circuit_open_seconds)
            # A page that never settled is not a page we may read as a note
            # — that is the whole point of waiting for stillness. But it is
            # still the only evidence of what the portal is showing, and
            # the commonest reason a portal never settles is that it is
            # showing a challenge: a Turnstile widget redraws itself for as
            # long as nobody clicks it. So it comes back attached to the
            # timeout, for the caller to recognise a refusal in. The
            # outcome stays `timeout`, so nothing downstream can mistake it
            # for an answer.
            unsettled = await self._best_effort_html(target_id)
            page = (
                FetchedPage(url=url, status_code=200, html=unsettled, fetched_at=datetime.now(timezone.utc))
                if unsettled
                else None
            )
            # A challenge is the one page worth leaving on screen: it is
            # waiting for a person, and closing it takes away the thing
            # they would act on. The next attempt finds this same tab and
            # reads whatever they left in it, so nothing is leaked — the
            # tab is claimed or closed, never merely abandoned.
            keep = page is not None and keep_open is not None and keep_open(page)
            return FetchResult(
                "timeout",
                page=page,
                detail=(
                    "browser is waiting for you"
                    if keep
                    else f"browser did not answer in {self.timeout_seconds:.0f}s"
                ),
                kept_open=keep,
            )
        except (httpx.TransportError, OSError) as exc:
            # The browser was never reached, so the portal said nothing and
            # the circuit must not close on its behalf: an unconfigured or
            # stopped browser would otherwise lock the state out of the
            # HTTP fetcher too, which shares this gate and works fine.
            where = getattr(self.transport, "endpoint", "the browser")
            return FetchResult("portal_down", detail=f"browser unreachable at {where}: {exc}")
        except Exception as exc:  # noqa: BLE001 — the browser is a remote service
            await self.gate.record_failure(uf, self.circuit_failures, self.circuit_open_seconds)
            return FetchResult("portal_down", detail=f"browser error: {exc}")
        finally:
            # A tab left open is a tab that keeps running scripts, so it is
            # closed unless somebody is expected to use it.
            if target_id is not None and not keep:
                try:
                    await self.transport.close_tab(target_id)
                except Exception:  # noqa: BLE001
                    pass

        await self.gate.record_success(uf)
        page = FetchedPage(
            url=url, status_code=200, html=html, fetched_at=datetime.now(timezone.utc)
        )
        return FetchResult("page", page=page)


class HttpWsCdp:
    """`CdpTransport` over Chrome's own endpoints.

    `PUT /json/new?<url>` opens the tab — the target is the query string
    itself, and a GET is refused by current builds. Everything after
    that is the
    DevTools WebSocket, one command per call, because this needs exactly
    one round trip and a session would be more moving parts than the job
    deserves.

    Two details exist because a headful Chrome will not be reached
    directly. It binds DevTools to loopback and ignores
    `--remote-debugging-address` (that flag is headless-only), so the
    browser is reached through a forwarder sharing its network namespace
    — and then Chrome sees a request whose `Host` is the forwarder's, and
    refuses it. `Host: localhost` is sent explicitly, which is true of
    the connection Chrome actually accepts, and harmless when this does
    talk to a directly reachable browser.

    The `webSocketDebuggerUrl` Chrome reports echoes that same Host back,
    so it names `localhost` — unreachable from here, and yet the one name
    the upgrade request must carry. Rewriting it would fix the routing
    and break the Host. So the URL is left exactly as Chrome wrote it and
    the connection is pointed at our address instead.
    """

    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self.endpoint = self._base
        self._ws_urls: dict[str, str] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, headers={"Host": "localhost"})

    def _ws_target(self) -> tuple[str, int]:
        """Where to open the socket, as opposed to what the URL says. The
        URL is Chrome's and stays Chrome's, because the Host it carries is
        the one Chrome accepts; only the destination is ours."""
        parts = urlsplit(self._base)
        default = 443 if parts.scheme == "https" else 80
        return parts.hostname or "localhost", parts.port or default

    async def _ws_send(self, ws_url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        # Imported here so the dependency is only needed by instances that
        # actually enable browser fetching.
        import websockets

        host, port = self._ws_target()
        # `host`/`port` reach `loop.create_connection`, so the socket goes
        # to the browser we were configured with while the request keeps
        # the URL's own Host header.
        async with websockets.connect(
            ws_url,
            open_timeout=self._timeout,
            max_size=64 * 1024 * 1024,
            host=host,
            port=port,
        ) as ws:
            await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
            while True:
                message = json.loads(await ws.recv())
                if message.get("id") == 1:
                    if "error" in message:
                        raise RuntimeError(f"{method}: {message['error']}")
                    return message.get("result", {})

    async def open_tab(self, url: str) -> str:
        async with self._client() as client:
            # The target is the whole query string, not a `url=` parameter:
            # `PUT /json/new?<encoded url>`. Sent as `url=…` Chrome tries to
            # navigate to the literal string `url=https://…`, which is not a
            # URL — so it opens the tab, never navigates, and hands back an
            # empty document that looks for all the world like a portal
            # returning nothing. Chrome unescapes the query, so the target
            # is percent-encoded whole.
            response = await client.put(f"{self._base}/json/new?{quote(url, safe='')}")
            response.raise_for_status()
            return str(response.json()["id"])

    async def _ws_url(self, target_id: str) -> str:
        # Asked once per tab: the page is polled while it loads, and
        # `/json/list` grows with every target the browser holds.
        cached = self._ws_urls.get(target_id)
        if cached is not None:
            return cached
        async with self._client() as client:
            response = await client.get(f"{self._base}/json/list")
            response.raise_for_status()
            for target in response.json():
                if str(target.get("id")) == target_id:
                    found = str(target["webSocketDebuggerUrl"])
                    self._ws_urls[target_id] = found
                    return found
        raise RuntimeError(f"tab {target_id} is gone")

    async def evaluate(self, target_id: str, expression: str) -> Any:
        result = await self._ws_send(
            await self._ws_url(target_id),
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
        if "exceptionDetails" in result:
            raise RuntimeError(f"the tab refused the expression: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    async def close_tab(self, target_id: str) -> None:
        self._ws_urls.pop(target_id, None)
        async with self._client() as client:
            await client.get(f"{self._base}/json/close/{target_id}")

    async def list_tabs(self) -> list[tuple[str, str]]:
        """`GET /json/list`, filtered to pages.

        Chrome lists every target it holds — service workers, extension
        backgrounds, the browser itself — and only a page can be read or
        reused, so the rest is dropped here rather than by every caller.
        """
        async with self._client() as client:
            response = await client.get(f"{self._base}/json/list")
            response.raise_for_status()
            targets = response.json()
        if not isinstance(targets, list):
            return []
        return [
            (str(t["id"]), str(t.get("url") or ""))
            for t in targets
            if isinstance(t, dict) and t.get("type") == "page" and t.get("id")
        ]
