"""What a state adapter is, and what it is not.

An adapter does two things: says what *kind* of page the portal returned,
and turns an authorised page into the canonical model. It does not fetch
(the `fetcher` does, with the allowlist the adapter declares) and it does
not persist (the service does). That is what makes one testable with a
saved `.html` and nothing else — and what makes a portal layout change
break a fixture test rather than production.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.receipts.canonical import CanonicalReceipt
from app.receipts.qr import QrPayload


class PageKind(StrEnum):
    #: The full DANFE: safe to parse.
    AUTHORIZED = "authorized"
    #: The key is fine, the portal just does not have the note yet.
    NOT_FOUND_YET = "not_found_yet"
    #: The note exists and was cancelled.
    CANCELLED = "cancelled"
    #: The portal asked for a human. Automatic retries are pointless;
    #: the user can paste the page instead.
    CAPTCHA = "captcha"
    #: Maintenance, 5xx, or HTML we do not recognise at all.
    ERROR_PAGE = "error_page"


@dataclass(frozen=True)
class FetchedPage:
    url: str
    status_code: int
    html: str
    fetched_at: datetime


class ParseError(Exception):
    """The page looked authorised but could not be read. `code` is stable
    (`no_items`, `no_totals`, `layout_changed`, …) and becomes
    `status_reason`; the message is for `last_error`."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


class UFAdapter(Protocol):
    c_uf: str
    uf: str
    #: Bumped whenever `parse` changes what it produces. Lets a later pass
    #: reprocess only the receipts an older parser read.
    parser_version: int
    #: Hosts the fetcher may contact on this adapter's behalf. The QR URL
    #: is user input; this is the boundary that keeps the scan endpoint
    #: from being a proxy.
    allowed_hosts: frozenset[str]

    def consulta_url(self, qr: QrPayload) -> str: ...

    def classify(self, page: FetchedPage) -> PageKind: ...

    def parse(self, html: str) -> CanonicalReceipt: ...
