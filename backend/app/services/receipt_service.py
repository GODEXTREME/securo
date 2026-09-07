"""Consumer receipts: scanning, the fetch state machine, and everything the
API and the worker do to a `Receipt`.

The only layer that touches the database for receipts. The parser and the
adapters are pure; the fetcher does HTTP; this module decides what a
result *means* and writes it down.
"""
from __future__ import annotations

import gzip
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, cast

from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.receipt import Receipt, ReceiptItem, ReceiptLink
from app.models.store import Store
from app.models.transaction import Transaction
from app.receipts.adapters.base import FetchedPage, PageKind, ParseError, UFAdapter
from app.receipts.adapters.registry import ADAPTERS
from app.receipts.canonical import CanonicalReceipt
from app.receipts.fetcher import Fetcher, host_allowed
from app.receipts.pasted import normalize_pasted
from app.receipts.qr import NFCE_MODEL, QrPayload, parse_access_key, parse_qr_payload
from app.receipts.adapters.tabresult import looks_like_html, parse_tabresult_text
from app.services import notification_service, price_service

#: Wait after the n-th failed attempt. Eight attempts in all (one immediate,
#: seven retries), about 45 hours end to end: a note that is not published
#: two days after the sale is not going to be, and the user can retry by hand.
RETRY_SCHEDULE: tuple[timedelta, ...] = (
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
    timedelta(hours=12),
    timedelta(hours=24),
)
#: Throttled by the portal: try again soon, and do not spend an attempt on it.
RATE_LIMIT_BACKOFF = timedelta(seconds=30)
#: A worker that has held a claim this long has died with it.
LOCK_STALE = timedelta(minutes=10)

#: Statuses the worker may claim. `fetching` is included so a stale lock
#: from a crashed worker is picked up; `parse_error` so an improved parser
#: can re-read the stored page.
CLAIMABLE = ("pending", "waiting_sefaz", "fetching", "parse_error")
#: What the "waiting on the state" block lists.
PENDING_STATUSES = ("pending", "fetching", "waiting_sefaz", "parse_error", "gave_up")
RETRYABLE = ("waiting_sefaz", "gave_up", "parse_error", "invalid")


class ReceiptError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class ScanOutcome:
    receipt: Receipt
    link: ReceiptLink
    created: bool
    already_linked: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rejection(
    *, tp_amb: int, model: str, c_uf: str, qr_url: Optional[str], adapters: dict[str, UFAdapter]
) -> Optional[str]:
    """Why a valid key will never be fetched, or None. Evaluated at scan and
    again on manual retry, so a state gaining an adapter revives its notes."""
    if tp_amb == 2:
        return "homolog"
    if model != NFCE_MODEL:
        return "not_nfce"
    adapter = adapters.get(c_uf)
    if adapter is None:
        return "unsupported_uf"
    if qr_url and not host_allowed(qr_url, adapter.allowed_hosts):
        return "unsupported_host"
    return None


# ---------------------------------------------------------------------------
# scanning and linking
# ---------------------------------------------------------------------------
async def scan(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    payload_text: str,
    *,
    adapters: dict[str, UFAdapter] = ADAPTERS,
    now: Optional[datetime] = None,
) -> ScanOutcome:
    """Turn whatever the user scanned or typed into a linked receipt.

    Raises `QrError` for input that is not a key at all. A valid key that
    policy refuses (homologation, NF-e, a state without an adapter) is
    persisted as `invalid` so the user sees it in the list with the reason.
    """
    now = now or _now()
    payload = parse_qr_payload(payload_text)
    key = payload.key
    receipt = await session.scalar(select(Receipt).where(Receipt.access_key == key.key))
    created = False
    if receipt is None:
        reason = _rejection(
            tp_amb=payload.tp_amb, model=key.model, c_uf=key.c_uf, qr_url=payload.url, adapters=adapters
        )
        receipt = Receipt(
            access_key=key.key,
            c_uf=key.c_uf,
            uf=key.uf,
            model=key.model,
            series=key.series,
            number=key.number,
            tp_amb=payload.tp_amb,
            tp_emis=key.tp_emis,
            qr_version=payload.version,
            issuer_cnpj=key.issuer_cnpj,
            qr_url=payload.url,
            status="invalid" if reason else "pending",
            status_reason=reason,
            next_attempt_at=None if reason else now,
            first_scanned_at=now,
        )
        session.add(receipt)
        await session.flush()
        created = True
    elif receipt.qr_url is None and payload.url:
        # A key typed first and its QR scanned later: keep the signed URL,
        # it is the one the portal answers without a challenge.
        receipt.qr_url = payload.url
        receipt.qr_version = payload.version or receipt.qr_version

    link = await session.scalar(
        select(ReceiptLink).where(
            ReceiptLink.receipt_id == receipt.id, ReceiptLink.workspace_id == workspace_id
        )
    )
    already_linked = link is not None
    if link is None:
        link = ReceiptLink(
            receipt_id=receipt.id, workspace_id=workspace_id, user_id=user_id, scanned_at=now
        )
        session.add(link)
        await session.flush()
        if receipt.status == "authorized":
            await session.refresh(receipt)
            link.variation_summary = await price_service.compute_variation(session, receipt, workspace_id)
    await session.commit()
    await session.refresh(receipt)
    await session.refresh(link)
    return ScanOutcome(receipt=receipt, link=link, created=created, already_linked=already_linked)


async def get_link(
    session: AsyncSession, workspace_id: uuid.UUID, receipt_id: uuid.UUID
) -> Optional[ReceiptLink]:
    """The workspace's view of a receipt, or None — which the API turns into
    404 so an unlinked note's existence is not revealed."""
    return await session.scalar(
        select(ReceiptLink)
        .options(
            selectinload(ReceiptLink.receipt).selectinload(Receipt.items),
            selectinload(ReceiptLink.receipt).selectinload(Receipt.links),
            selectinload(ReceiptLink.receipt).selectinload(Receipt.store),
        )
        .where(ReceiptLink.receipt_id == receipt_id, ReceiptLink.workspace_id == workspace_id)
    )


async def list_receipts(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    pending_only: bool = False,
    store_id: Optional[uuid.UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[tuple[Receipt, ReceiptLink]]:
    stmt = (
        select(Receipt, ReceiptLink)
        .join(ReceiptLink, ReceiptLink.receipt_id == Receipt.id)
        .where(ReceiptLink.workspace_id == workspace_id)
    )
    if status:
        stmt = stmt.where(Receipt.status == status)
    if pending_only:
        stmt = stmt.where(Receipt.status.in_(PENDING_STATUSES))
    if store_id:
        stmt = stmt.where(Receipt.store_id == store_id)
    anchor = func.coalesce(Receipt.issued_at, Receipt.first_scanned_at)
    if date_from:
        stmt = stmt.where(anchor >= date_from)
    if date_to:
        stmt = stmt.where(anchor <= date_to)
    stmt = stmt.order_by(anchor.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def retry(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    receipt_id: uuid.UUID,
    *,
    adapters: dict[str, UFAdapter] = ADAPTERS,
    now: Optional[datetime] = None,
) -> Optional[Receipt]:
    """Put a stuck receipt back in the queue. `gave_up` gets a fresh
    schedule; `invalid` is re-evaluated in case the reason went away."""
    now = now or _now()
    link = await get_link(session, workspace_id, receipt_id)
    if link is None:
        return None
    receipt = link.receipt
    if receipt.status not in RETRYABLE:
        raise ReceiptError("not_retryable", f"status is {receipt.status}")
    if receipt.status == "invalid":
        reason = _rejection(
            tp_amb=receipt.tp_amb, model=receipt.model, c_uf=receipt.c_uf,
            qr_url=receipt.qr_url, adapters=adapters,
        )
        if reason is not None:
            raise ReceiptError("still_invalid", reason)
    if receipt.status == "gave_up":
        receipt.attempts = 0
    receipt.status = "pending"
    receipt.status_reason = None
    receipt.next_attempt_at = now
    receipt.locked_at = None
    await session.commit()
    await session.refresh(receipt)
    return receipt


async def submit_html(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    receipt_id: uuid.UUID,
    html: str,
    *,
    adapters: dict[str, UFAdapter] = ADAPTERS,
    now: Optional[datetime] = None,
) -> Receipt:
    """The escape hatch for a portal that wants a human: the user opened the
    page in a browser and pasted it. Same parser, same validation."""
    now = now or _now()
    link = await get_link(session, workspace_id, receipt_id)
    if link is None:
        raise ReceiptError("not_found")
    receipt = link.receipt
    adapter = adapters.get(receipt.c_uf)
    if adapter is None:
        raise ReceiptError("unsupported_uf")
    html = normalize_pasted(html)
    if not looks_like_html(html):
        # What a phone gives after "select all → copy": the rendered text.
        # Every adapter today is the tabResult template, whose labels
        # survive the copy, so one text parser serves them all for now.
        try:
            canonical = parse_tabresult_text(html, expected_uf=receipt.uf)
            _check_key(receipt, canonical)
        except ParseError as exc:
            raise ReceiptError(exc.code, str(exc)) from exc
        await _apply_canonical(
            session, receipt, canonical, html, source="pasted_text",
            parser_version=adapter.parser_version, now=now,
        )
        await session.commit()
        await session.refresh(receipt)
        return receipt
    page = FetchedPage(url=receipt.qr_url or "", status_code=200, html=html, fetched_at=now)
    kind = adapter.classify(page)
    if kind == PageKind.CANCELLED:
        receipt.status = "cancelled"
        receipt.status_reason = "cancelled_by_sefaz"
        await price_service.void_points(session, receipt, now=now)
        _store_raw(receipt, html, now)
        await session.commit()
        await session.refresh(receipt)
        return receipt
    if kind != PageKind.AUTHORIZED:
        raise ReceiptError(f"page_{kind.value}")
    try:
        canonical = adapter.parse(html)
        _check_key(receipt, canonical)
    except ParseError as exc:
        raise ReceiptError(exc.code, str(exc)) from exc
    await _apply_canonical(
        session, receipt, canonical, html, source="pasted_html",
        parser_version=adapter.parser_version, now=now,
    )
    await session.commit()
    await session.refresh(receipt)
    return receipt


async def update_link(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    receipt_id: uuid.UUID,
    *,
    not_my_purchase: Optional[bool] = None,
    transaction_id: Optional[uuid.UUID] = None,
    clear_transaction: bool = False,
) -> Optional[ReceiptLink]:
    link = await get_link(session, workspace_id, receipt_id)
    if link is None:
        return None
    if not_my_purchase is not None:
        link.not_my_purchase = not_my_purchase
    if clear_transaction:
        link.transaction_id = None
    elif transaction_id is not None:
        owned = await session.scalar(
            select(Transaction.id).where(
                Transaction.id == transaction_id, Transaction.workspace_id == workspace_id
            )
        )
        if owned is None:
            raise ReceiptError("transaction_not_found")
        link.transaction_id = transaction_id
    await session.commit()
    await session.refresh(link)
    return link


async def update_item(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    receipt_id: uuid.UUID,
    ordinal: int,
    *,
    unit_price_corrected: Optional[Decimal],
    now: Optional[datetime] = None,
) -> Optional[ReceiptItem]:
    link = await get_link(session, workspace_id, receipt_id)
    if link is None:
        return None
    item = next((i for i in link.receipt.items if i.ordinal == ordinal), None)
    if item is None:
        return None
    item.unit_price_corrected = unit_price_corrected
    item.corrected_at = (now or _now()) if unit_price_corrected is not None else None
    await session.flush()
    receipt = link.receipt
    if receipt.status == "authorized":
        await price_service.enrich_receipt(session, receipt)
        await price_service.refresh_variations(session, receipt)
    await session.commit()
    await session.refresh(item)
    return item


async def unlink(session: AsyncSession, workspace_id: uuid.UUID, receipt_id: uuid.UUID) -> bool:
    """Forget that this workspace scanned the note. The note stays."""
    link = await get_link(session, workspace_id, receipt_id)
    if link is None:
        return False
    await session.delete(link)
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# the worker's side
# ---------------------------------------------------------------------------
async def due_receipt_ids(
    session: AsyncSession, *, now: Optional[datetime] = None, limit: int = 50
) -> list[uuid.UUID]:
    """What the sweep dispatches: due and unclaimed, or claimed by a worker
    that has evidently died."""
    now = now or _now()
    stale = now - LOCK_STALE
    stmt = (
        select(Receipt.id)
        .where(
            or_(
                Receipt.status.in_(("pending", "waiting_sefaz"))
                & (Receipt.next_attempt_at.is_not(None))
                & (Receipt.next_attempt_at <= now)
                & or_(Receipt.locked_at.is_(None), Receipt.locked_at < stale),
                (Receipt.status == "fetching") & (Receipt.locked_at < stale),
            )
        )
        .order_by(Receipt.next_attempt_at)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def stale_parse_error_ids(
    session: AsyncSession, *, adapters: dict[str, UFAdapter] = ADAPTERS, limit: int = 50
) -> list[uuid.UUID]:
    """Receipts an older parser failed on, whose stored page a newer one
    should re-read. Requeued without touching the portal."""
    rows = (
        await session.execute(
            select(Receipt.id, Receipt.c_uf, Receipt.parser_version)
            .where(Receipt.status == "parse_error", Receipt.raw_html.is_not(None))
            .limit(limit * 4)
        )
    ).all()
    out: list[uuid.UUID] = []
    for receipt_id, c_uf, version in rows:
        adapter = adapters.get(c_uf)
        if adapter is not None and (version or 0) < adapter.parser_version:
            out.append(receipt_id)
            if len(out) >= limit:
                break
    return out


async def process_receipt(
    session: AsyncSession,
    receipt_id: uuid.UUID,
    *,
    fetcher: Fetcher,
    adapters: dict[str, UFAdapter] = ADAPTERS,
    now: Optional[datetime] = None,
    raw_ttl_days: Optional[int] = None,
) -> Optional[Receipt]:
    """One attempt. Claims the row, fetches (or re-reads the stored page),
    classifies, parses, and writes the resulting state. Returns None when
    another worker holds the claim."""
    now = now or _now()
    previous = await session.scalar(select(Receipt.status).where(Receipt.id == receipt_id))
    if previous is None:
        return None
    claim = await session.execute(
        update(Receipt)
        .where(
            Receipt.id == receipt_id,
            Receipt.status.in_(CLAIMABLE),
            or_(Receipt.locked_at.is_(None), Receipt.locked_at < now - LOCK_STALE),
        )
        .values(status="fetching", locked_at=now)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult, claim).rowcount == 0:
        # Someone else holds it. Nothing was written; end the transaction
        # without expiring the caller's objects (rollback would).
        await session.commit()
        return None
    await session.commit()

    receipt = await session.get(Receipt, receipt_id)
    assert receipt is not None
    # The claim above bypassed identity-map synchronisation; the object in
    # hand may predate it (the worker's session does not expire on commit).
    # Read it back so `locked_at`/`status` are the row's, not a memory of it.
    await session.refresh(receipt)
    try:
        adapter = adapters.get(receipt.c_uf)
        if adapter is None:
            _finish_invalid(receipt, "unsupported_uf")
            return receipt

        page: Optional[FetchedPage] = None
        if previous == "parse_error" and receipt.raw_html:
            page = FetchedPage(
                url=receipt.qr_url or "", status_code=200,
                html=gzip.decompress(receipt.raw_html).decode("utf-8", errors="replace"),
                fetched_at=receipt.raw_fetched_at or now,
            )
        else:
            url = receipt.qr_url or adapter.consulta_url(_payload_from(receipt))
            result = await fetcher.fetch(url, adapter.allowed_hosts, receipt.uf)
            if result.outcome == "blocked":
                _finish_invalid(receipt, "unsupported_host", result.detail)
                return receipt
            if result.outcome == "rate_limited":
                _reschedule(receipt, "rate_limited", now, detail=result.detail, count=False)
                return receipt
            if result.outcome in ("portal_down", "timeout", "http_error"):
                _reschedule(receipt, result.outcome, now, detail=result.detail)
                if result.page is not None:
                    _store_raw(receipt, result.page.html, now, ttl_days=raw_ttl_days)
                return receipt
            page = result.page
            if page is None:
                _reschedule(receipt, "portal_down", now, detail="no page")
                return receipt

        kind = adapter.classify(page)
        if kind == PageKind.AUTHORIZED:
            try:
                canonical = adapter.parse(page.html)
                _check_key(receipt, canonical)
            except ParseError as exc:
                receipt.status = "parse_error"
                receipt.status_reason = "parser_failed" if exc.code != "key_mismatch" else "key_mismatch"
                receipt.last_error = f"{exc.code}: {exc}"
                receipt.parser_version = adapter.parser_version
                receipt.next_attempt_at = None
                _store_raw(receipt, page.html, now, ttl_days=raw_ttl_days)
                return receipt
            await _apply_canonical(
                session, receipt, canonical, page.html, source="sefaz_html",
                parser_version=adapter.parser_version, now=now, raw_ttl_days=raw_ttl_days,
            )
            return receipt
        # Every page we could not use is kept too: it is the only evidence of
        # what the portal actually said, and the TTL bounds the cost.
        if kind != PageKind.AUTHORIZED:
            _store_raw(receipt, page.html, now, ttl_days=raw_ttl_days)
        if kind == PageKind.NOT_FOUND_YET:
            _reschedule(receipt, "not_published", now)
        elif kind == PageKind.CANCELLED:
            receipt.status = "cancelled"
            receipt.status_reason = "cancelled_by_sefaz"
            receipt.next_attempt_at = None
            await price_service.void_points(session, receipt, now=now)
        elif kind == PageKind.CAPTCHA:
            # No automatic retry: the portal wants a person. The UI offers
            # "paste the page" for exactly this state.
            receipt.status = "waiting_sefaz"
            receipt.status_reason = "captcha"
            receipt.next_attempt_at = None
            receipt.last_error = "portal presented a challenge"
        else:
            snippet = " ".join(page.html.split())[:160]
            _reschedule(
                receipt, "portal_down", now,
                detail=f"unrecognised page from {page.url} (HTTP {page.status_code}): {snippet}",
            )
        return receipt
    finally:
        receipt.locked_at = None
        await session.commit()


async def expire_raw_html(session: AsyncSession, *, now: Optional[datetime] = None) -> int:
    now = now or _now()
    result = await session.execute(
        update(Receipt)
        .where(Receipt.raw_html.is_not(None), Receipt.raw_expires_at.is_not(None), Receipt.raw_expires_at <= now)
        .values(raw_html=None)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return cast(CursorResult, result).rowcount


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _payload_from(receipt: Receipt) -> QrPayload:
    return QrPayload(
        key=parse_access_key(receipt.access_key), url=receipt.qr_url, version=receipt.qr_version,
        tp_amb=receipt.tp_amb, c_id_token=None, signature=None,
    )


def _check_key(receipt: Receipt, canonical: CanonicalReceipt) -> None:
    if canonical.access_key != receipt.access_key:
        raise ParseError("key_mismatch", f"page is for {canonical.access_key}")


def _finish_invalid(receipt: Receipt, reason: str, detail: Optional[str] = None) -> None:
    receipt.status = "invalid"
    receipt.status_reason = reason
    receipt.next_attempt_at = None
    receipt.last_error = detail


def _reschedule(
    receipt: Receipt, reason: str, now: datetime, *, detail: Optional[str] = None, count: bool = True
) -> None:
    receipt.status_reason = reason
    receipt.last_error = detail
    if not count:
        receipt.status = "waiting_sefaz"
        receipt.next_attempt_at = now + RATE_LIMIT_BACKOFF
        return
    receipt.attempts = (receipt.attempts or 0) + 1
    if receipt.attempts > len(RETRY_SCHEDULE):
        receipt.status = "gave_up"
        receipt.next_attempt_at = None
        return
    receipt.status = "waiting_sefaz"
    receipt.next_attempt_at = now + RETRY_SCHEDULE[receipt.attempts - 1]


def _store_raw(receipt: Receipt, html: str, now: datetime, *, ttl_days: Optional[int] = None) -> None:
    ttl = ttl_days if ttl_days is not None else get_settings().receipts_raw_html_ttl_days
    receipt.raw_html = gzip.compress(html.encode("utf-8"))
    receipt.raw_fetched_at = now
    receipt.raw_expires_at = now + timedelta(days=ttl)


def _cpf_hash(cpf: Optional[str]) -> Optional[str]:
    if not cpf:
        return None
    salt = get_settings().secret_key.get_secret_value()
    return hashlib.sha256(f"{salt}:{cpf}".encode("utf-8")).hexdigest()


async def _upsert_store(session: AsyncSession, canonical: CanonicalReceipt, now: datetime) -> Store:
    issuer = canonical.issuer
    store = await session.scalar(select(Store).where(Store.cnpj == issuer.cnpj))
    if store is None:
        store = Store(cnpj=issuer.cnpj, cnpj_root=issuer.cnpj[:8], legal_name=issuer.legal_name, first_seen_at=now)
        session.add(store)
    store.legal_name = issuer.legal_name or store.legal_name
    store.trade_name = issuer.trade_name or store.trade_name
    store.ie = issuer.ie or store.ie
    store.street = issuer.street or store.street
    store.number = issuer.number or store.number
    store.district = issuer.district or store.district
    store.city = issuer.city or store.city
    store.uf = issuer.uf or store.uf
    store.zip = issuer.zip or store.zip
    store.last_seen_at = now
    await session.flush()
    return store


async def _apply_canonical(
    session: AsyncSession,
    receipt: Receipt,
    canonical: CanonicalReceipt,
    html: str,
    *,
    source: str,
    parser_version: int,
    now: datetime,
    raw_ttl_days: Optional[int] = None,
) -> None:
    store = await _upsert_store(session, canonical, now)
    receipt.store_id = store.id
    receipt.series = canonical.series
    receipt.number = canonical.number
    receipt.issued_at = canonical.issued_at
    receipt.issued_on = canonical.issued_at.date() if canonical.issued_at else None
    receipt.authorized_at = canonical.authorized_at
    receipt.protocol = canonical.protocol
    receipt.items_count = canonical.totals.items_count
    receipt.products_total = canonical.totals.products_total
    receipt.discount = canonical.totals.discount
    receipt.addition = canonical.totals.addition
    receipt.shipping = canonical.totals.shipping
    receipt.total = canonical.totals.total
    receipt.approx_taxes = canonical.totals.approx_taxes
    receipt.payments = [
        {
            "type": p.type, "label": p.label, "brand": p.brand,
            "amount": float(p.amount), "change": float(p.change),
        }
        for p in canonical.payments
    ]
    receipt.customer_cpf_hash = _cpf_hash(canonical.customer_cpf)
    receipt.parser_version = parser_version
    receipt.source = source
    receipt.status = "authorized"
    receipt.status_reason = None
    receipt.last_error = None
    receipt.next_attempt_at = None

    # Reprocessing replaces the item rows; the unique (receipt, ordinal)
    # constraint means an in-place update would collide with itself.
    receipt.items.clear()
    await session.flush()
    for item in canonical.items:
        receipt.items.append(
            ReceiptItem(
                ordinal=item.ordinal,
                product_code=item.product_code,
                gtin=item.gtin,
                description=item.description,
                ncm=item.ncm,
                cfop=item.cfop,
                unit=item.unit,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total=item.total,
                discount=item.discount,
            )
        )
    _store_raw(receipt, html, now, ttl_days=raw_ttl_days)
    await session.flush()
    await session.refresh(receipt, ["items", "links"])

    # The whole point: lines → products → price points → "vs. last time".
    await price_service.enrich_receipt(session, receipt)
    await price_service.refresh_variations(session, receipt)

    for link in receipt.links:
        await notification_service.create_notification(
            session,
            link.workspace_id,
            link.user_id,
            type="receipt_processed",
            title=f"Receipt from {store.trade_name or store.legal_name}",
            body=f"{receipt.items_count} items · R$ {receipt.total:.2f}",
            link=f"/receipts/{receipt.id}",
            dedup_key=f"receipt:{receipt.id}:processed",
        )
