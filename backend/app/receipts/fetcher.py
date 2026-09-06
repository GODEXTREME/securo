"""The only code that contacts a state portal.

Everything that protects the portal, and everything that protects us,
lives here and nowhere else:

  - **Allowlist.** The URL came out of a QR code the user scanned, which
    makes it user input. The host must match the adapter's declared hosts
    exactly, the scheme must be http(s), redirects are followed by hand
    and only to allowed hosts, and the name must not resolve to a private
    address. Without this, `POST /scan` is a proxy into the network.
  - **Rate limit** per host: one request every `min_interval_ms`, shared
    across workers through Redis.
  - **Circuit breaker** per state: `circuit_failures` consecutive
    timeouts/5xx open it for `circuit_open_seconds`, during which nothing
    is sent and the receipt is simply rescheduled.
  - A short timeout and an identifiable User-Agent.

The gate (rate limit + circuit) is an injected object so the module is
tested with an in-memory one; production uses Redis.
"""
from __future__ import annotations

import asyncio
import ipaddress
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal, Optional, Protocol
from urllib.parse import urljoin, urlsplit

import httpx
import redis.asyncio as redis_asyncio

from app.receipts.adapters.base import FetchedPage

Outcome = Literal["page", "blocked", "portal_down", "rate_limited", "http_error", "timeout"]


@dataclass(frozen=True)
class FetchResult:
    outcome: Outcome
    page: Optional[FetchedPage] = None
    #: Free text for `last_error`; the outcome is what the state machine reads.
    detail: Optional[str] = None


class Gate(Protocol):
    async def acquire(self, host: str, min_interval_ms: int) -> bool: ...
    async def circuit_open(self, uf: str) -> bool: ...
    async def record_failure(self, uf: str, threshold: int, open_seconds: int) -> None: ...
    async def record_success(self, uf: str) -> None: ...


class MemoryGate:
    """Single-process gate for tests and for running without Redis."""

    def __init__(self) -> None:
        self._next_allowed: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    async def acquire(self, host: str, min_interval_ms: int) -> bool:
        now = time.monotonic()
        if self._next_allowed.get(host, 0.0) > now:
            return False
        self._next_allowed[host] = now + min_interval_ms / 1000
        return True

    async def circuit_open(self, uf: str) -> bool:
        return self._open_until.get(uf, 0.0) > time.monotonic()

    async def record_failure(self, uf: str, threshold: int, open_seconds: int) -> None:
        count = self._failures.get(uf, 0) + 1
        self._failures[uf] = count
        if count >= threshold:
            self._open_until[uf] = time.monotonic() + open_seconds
            self._failures[uf] = 0

    async def record_success(self, uf: str) -> None:
        self._failures.pop(uf, None)


class RedisGate:
    """Shared gate: two workers on two hosts still send one request per
    interval and open the same circuit."""

    def __init__(self, redis: redis_asyncio.Redis) -> None:
        self._redis = redis

    async def acquire(self, host: str, min_interval_ms: int) -> bool:
        ok = await self._redis.set(f"receipts:rl:{host}", "1", nx=True, px=min_interval_ms)
        return bool(ok)

    async def circuit_open(self, uf: str) -> bool:
        return bool(await self._redis.exists(f"receipts:cb:{uf}:open"))

    async def record_failure(self, uf: str, threshold: int, open_seconds: int) -> None:
        key = f"receipts:cb:{uf}:failures"
        count = int(await self._redis.incr(key))
        await self._redis.expire(key, open_seconds)
        if count >= threshold:
            await self._redis.set(f"receipts:cb:{uf}:open", "1", ex=open_seconds)
            await self._redis.delete(key)

    async def record_success(self, uf: str) -> None:
        await self._redis.delete(f"receipts:cb:{uf}:failures")


Resolver = Callable[[str], Awaitable[bool]]


async def resolves_to_private(host: str) -> bool:
    """True when any address the name resolves to is not a public one.
    A name that does not resolve at all is treated as private: we would
    rather refuse a portal that is down than connect to something odd."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError:
        return True
    if not infos:
        return True
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast or address.is_unspecified
        ):
            return True
    return False


def host_allowed(url: str, allowed_hosts: frozenset[str]) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    return parts.hostname.lower() in allowed_hosts


class Fetcher:
    def __init__(
        self,
        gate: Gate,
        *,
        timeout_seconds: float = 15.0,
        min_interval_ms: int = 2000,
        circuit_failures: int = 5,
        circuit_open_seconds: int = 900,
        user_agent: str = "Securo/receipts",
        max_redirects: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = resolves_to_private,
    ) -> None:
        self._gate = gate
        self._timeout = timeout_seconds
        self._min_interval_ms = min_interval_ms
        self._circuit_failures = circuit_failures
        self._circuit_open_seconds = circuit_open_seconds
        self._user_agent = user_agent
        self._max_redirects = max_redirects
        self._transport = transport
        self._resolver = resolver

    async def fetch(self, url: str, allowed_hosts: frozenset[str], uf: str) -> FetchResult:
        if not host_allowed(url, allowed_hosts):
            return FetchResult("blocked", detail=f"host not allowed for {uf}: {url}")
        if await self._gate.circuit_open(uf):
            return FetchResult("portal_down", detail=f"circuit open for {uf}")

        # One token per fetch, not per hop: a portal's http→https redirect
        # is not a second request from the portal's point of view.
        first_host = urlsplit(url).hostname or ""
        if not await self._gate.acquire(first_host, self._min_interval_ms):
            return FetchResult("rate_limited", detail=f"interval not elapsed for {first_host}")

        current = url
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            headers={"User-Agent": self._user_agent, "Accept": "text/html,*/*;q=0.5"},
            transport=self._transport,
        ) as client:
            for _ in range(self._max_redirects + 1):
                host = urlsplit(current).hostname or ""
                if await self._resolver(host):
                    return FetchResult("blocked", detail=f"{host} resolves to a private address")
                try:
                    response = await client.get(current)
                except httpx.TimeoutException:
                    await self._fail(uf)
                    return FetchResult("timeout", detail=f"timeout after {self._timeout}s")
                except httpx.HTTPError as exc:
                    await self._fail(uf)
                    return FetchResult("portal_down", detail=f"{type(exc).__name__}: {exc}")

                if 300 <= response.status_code < 400 and response.headers.get("location"):
                    target = urljoin(current, response.headers["location"])
                    if not host_allowed(target, allowed_hosts):
                        return FetchResult("blocked", detail=f"redirect to disallowed host: {target}")
                    current = target
                    continue
                if response.status_code == 429:
                    await self._fail(uf)
                    return FetchResult("rate_limited", detail="portal answered 429")
                if response.status_code >= 500:
                    await self._fail(uf)
                    return FetchResult(
                        "portal_down",
                        page=self._page(current, response),
                        detail=f"portal answered {response.status_code}",
                    )
                if response.status_code >= 400:
                    return FetchResult(
                        "http_error",
                        page=self._page(current, response),
                        detail=f"portal answered {response.status_code}",
                    )
                await self._gate.record_success(uf)
                return FetchResult("page", page=self._page(current, response))
        return FetchResult("blocked", detail="too many redirects")

    async def _fail(self, uf: str) -> None:
        await self._gate.record_failure(uf, self._circuit_failures, self._circuit_open_seconds)

    @staticmethod
    def _page(url: str, response: httpx.Response) -> FetchedPage:
        return FetchedPage(
            url=url,
            status_code=response.status_code,
            html=response.text,
            fetched_at=datetime.now(timezone.utc),
        )
