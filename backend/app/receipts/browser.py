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
from typing import Any, Optional, Protocol
from urllib.parse import urlsplit

import httpx

from app.receipts.adapters.base import FetchedPage
from app.receipts.fetcher import FetchResult, Gate, host_allowed

#: How long to let a page settle before reading it. The portals' own
#: scripts run in well under a second; this is slack for a cold browser.
SETTLE_SECONDS = 3.0


class CdpTransport(Protocol):
    """The three things this needs from a browser. Implemented over HTTP
    and a WebSocket below; replaced wholesale in tests."""

    #: Where this transport expects the browser to be. Only ever used in
    #: an error message — and it is the one fact that message needs, since
    #: the first thing that goes wrong is pointing at the wrong address.
    endpoint: str

    async def open_tab(self, url: str) -> str:
        """Navigate a new tab to `url`. Returns its target id."""

    async def outer_html(self, target_id: str) -> str:
        """The document as the browser has it, after scripts have run."""

    async def close_tab(self, target_id: str) -> None:
        ...


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
    circuit_failures: int = 5
    circuit_open_seconds: int = 900

    async def fetch(self, url: str, allowed_hosts: frozenset[str], uf: str) -> FetchResult:
        if not host_allowed(url, allowed_hosts):
            return FetchResult("blocked", detail=f"host not allowed for {uf}: {url}")
        if await self.gate.circuit_open(uf):
            return FetchResult("portal_down", detail=f"circuit open for {uf}")

        target_id: Optional[str] = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                target_id = await self.transport.open_tab(url)
                # The page is served immediately and rewritten by its own
                # scripts; reading too early gets the interstitial.
                await asyncio.sleep(self.settle_seconds)
                html = await self.transport.outer_html(target_id)
        except asyncio.TimeoutError:
            await self.gate.record_failure(uf, self.circuit_failures, self.circuit_open_seconds)
            return FetchResult("timeout", detail=f"browser did not answer in {self.timeout_seconds:.0f}s")
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
            if target_id is not None:
                # A tab left open is a tab that keeps running scripts.
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

    `PUT /json/new?url=` opens the tab — a GET was accepted by older
    builds and is refused by current ones. Everything after that is the
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
            response = await client.put(f"{self._base}/json/new", params={"url": url})
            response.raise_for_status()
            return str(response.json()["id"])

    async def _ws_url(self, target_id: str) -> str:
        async with self._client() as client:
            response = await client.get(f"{self._base}/json/list")
            response.raise_for_status()
            for target in response.json():
                if str(target.get("id")) == target_id:
                    return str(target["webSocketDebuggerUrl"])
        raise RuntimeError(f"tab {target_id} is gone")

    async def outer_html(self, target_id: str) -> str:
        result = await self._ws_send(
            await self._ws_url(target_id),
            "Runtime.evaluate",
            {"expression": "document.documentElement.outerHTML", "returnByValue": True},
        )
        value = result.get("result", {}).get("value")
        if not isinstance(value, str):
            raise RuntimeError("the tab returned no HTML")
        return value

    async def close_tab(self, target_id: str) -> None:
        async with self._client() as client:
            await client.get(f"{self._base}/json/close/{target_id}")
