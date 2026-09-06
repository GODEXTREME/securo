"""Price points and what they answer: "did I pay more than last time?",
"where was it cheapest lately?", "what does this product's history look
like?".

Everything here reads the shared, anonymous `price_points`; anything
personal goes through `receipt_links` for one workspace. A cancelled
note voids its points; an implausible point stays in the history flagged
as an outlier and out of the answers.
"""
from __future__ import annotations

import statistics
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.price_point import PricePoint
from app.models.product import Product
from app.models.receipt import Receipt, ReceiptItem, ReceiptLink
from app.models.store import Store
from app.receipts.normalize import normalize_price, parse_size
from app.services import catalog_service

OUTLIER_HIGH = Decimal("10")
OUTLIER_LOW = Decimal("0.1")
OUTLIER_MIN_POINTS = 2
OUTLIER_WINDOW = timedelta(days=365)
BEST_PRICE_WINDOW_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value.quantize(Decimal("0.01")))


# ---------------------------------------------------------------------------
# enrichment: lines → products → points
# ---------------------------------------------------------------------------
async def enrich_receipt(session: AsyncSession, receipt: Receipt) -> int:
    """Resolve every line to a product, compute its normalised price, and
    upsert its price point. Idempotent: run it twice and nothing doubles.
    Returns the number of lines placed."""
    if receipt.status != "authorized" or receipt.store_id is None:
        return 0
    store = await session.get(Store, receipt.store_id)
    if store is None:
        return 0
    observed_on = receipt.issued_on or (receipt.issued_at.date() if receipt.issued_at else receipt.first_scanned_at.date())
    placed = 0
    for item in receipt.items:
        size = parse_size(item.description)
        item.size_value, item.size_unit, item.pack_count = size.value, size.unit, size.pack_count
        normalized = normalize_price(item.unit, item.quantity, item.effective_unit_price, size)
        item.normalized_price, item.base_unit, item.comparable = normalized.price, normalized.base_unit, normalized.comparable
        product = await catalog_service.resolve_product(
            session,
            description=item.description,
            unit=item.unit,
            gtin=item.gtin,
            product_code=item.product_code,
            cnpj_root=store.cnpj_root,
            size=size,
        )
        item.product_id = product.id
        await _upsert_point(session, receipt, item, product, store, observed_on)
        placed += 1
    await session.flush()
    return placed


async def _upsert_point(
    session: AsyncSession, receipt: Receipt, item: ReceiptItem, product: Product, store: Store, observed_on: date
) -> PricePoint:
    point = await session.scalar(select(PricePoint).where(PricePoint.receipt_item_id == item.id))
    if point is None:
        point = PricePoint(receipt_item_id=item.id, receipt_id=receipt.id, product_id=product.id, store_id=store.id)
        session.add(point)
    point.product_id = product.id
    point.store_id = store.id
    point.observed_on = observed_on
    point.unit = item.unit
    point.quantity = item.quantity
    point.unit_price = item.effective_unit_price
    point.normalized_price = item.normalized_price
    point.base_unit = item.base_unit
    point.comparable = item.comparable
    point.source = receipt.source or "sefaz_html"
    point.voided_at = None if receipt.status == "authorized" else _now()
    await session.flush()
    point.is_outlier = await _is_outlier(session, point)
    return point


async def _is_outlier(session: AsyncSession, point: PricePoint) -> bool:
    """Against the median of the product's other points in the last year.
    Needs at least two of them to have an opinion; a lone earlier point is
    not a baseline, it is one more observation."""
    value = point.normalized_price if point.normalized_price is not None else point.unit_price
    if value is None or value <= 0:
        return True
    rows = (
        await session.execute(
            select(PricePoint.normalized_price, PricePoint.unit_price, PricePoint.base_unit)
            .where(
                PricePoint.product_id == point.product_id,
                PricePoint.id != point.id,
                PricePoint.voided_at.is_(None),
                PricePoint.is_outlier.is_(False),
                PricePoint.observed_on >= point.observed_on - OUTLIER_WINDOW,
                PricePoint.observed_on <= point.observed_on,
            )
        )
    ).all()
    comparable = [
        (n if (n is not None and b == point.base_unit) else u)
        for n, u, b in rows
        if (n is not None and b == point.base_unit) or (n is None and point.normalized_price is None)
    ]
    if len(comparable) < OUTLIER_MIN_POINTS:
        return False
    median = Decimal(str(statistics.median([float(x) for x in comparable])))
    if median <= 0:
        return False
    ratio = value / median
    return ratio > OUTLIER_HIGH or ratio < OUTLIER_LOW


async def void_points(session: AsyncSession, receipt: Receipt, *, now: Optional[datetime] = None) -> int:
    result = await session.execute(
        update(PricePoint)
        .where(PricePoint.receipt_id == receipt.id, PricePoint.voided_at.is_(None))
        .values(voided_at=now or _now())
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult, result).rowcount


async def unenriched_receipt_ids(session: AsyncSession, *, limit: int = 50) -> list[uuid.UUID]:
    """Authorised notes with lines the matcher has not placed — notes that
    were authorised before the catalogue existed, or whose enrichment
    failed mid-way. The sweep picks them up."""
    stmt = (
        select(Receipt.id)
        .join(ReceiptItem, ReceiptItem.receipt_id == Receipt.id)
        .where(Receipt.status == "authorized", ReceiptItem.product_id.is_(None))
        .distinct()
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# variation: this receipt vs. what the workspace paid last time
# ---------------------------------------------------------------------------
async def _previous_point(
    session: AsyncSession, product_id: uuid.UUID, workspace_id: uuid.UUID, before: date, exclude_receipt: uuid.UUID
) -> Optional[tuple[PricePoint, Optional[str]]]:
    row = (
        await session.execute(
            select(PricePoint, Store.legal_name, Store.trade_name)
            .join(ReceiptLink, ReceiptLink.receipt_id == PricePoint.receipt_id)
            .join(Store, Store.id == PricePoint.store_id)
            .where(
                PricePoint.product_id == product_id,
                PricePoint.receipt_id != exclude_receipt,
                PricePoint.voided_at.is_(None),
                PricePoint.is_outlier.is_(False),
                PricePoint.comparable.is_(True),
                PricePoint.observed_on <= before,
                ReceiptLink.workspace_id == workspace_id,
                ReceiptLink.not_my_purchase.is_(False),
            )
            .order_by(PricePoint.observed_on.desc(), PricePoint.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    point, legal_name, trade_name = row
    return point, (trade_name or legal_name)


async def compute_variation(session: AsyncSession, receipt: Receipt, workspace_id: uuid.UUID) -> Optional[dict[str, Any]]:
    """Per line: the last comparable price this workspace paid for the same
    product, and the difference. Aggregated: "you paid R$ X more than if
    everything had been at last time's price", over compared lines only.
    None until at least one line has a product."""
    if receipt.status != "authorized":
        return None
    observed_on = receipt.issued_on or receipt.first_scanned_at.date()
    items_out: list[dict[str, Any]] = []
    delta_total = Decimal("0")
    compared = 0
    placed = 0
    for item in receipt.items:
        if item.product_id is None:
            continue
        placed += 1
        if not item.comparable:
            continue
        previous = await _previous_point(session, item.product_id, workspace_id, observed_on, receipt.id)
        if previous is None:
            continue
        point, store_name = previous
        current_unit = item.effective_unit_price
        if item.normalized_price and point.normalized_price and point.base_unit == item.base_unit and item.normalized_price > 0:
            # Compare per kilo/litre/unit and express the previous price in
            # this line's commercial unit so the delta reads on the receipt.
            factor = current_unit / item.normalized_price
            previous_unit = (point.normalized_price * factor).quantize(Decimal("0.0001"))
        elif point.unit == item.unit:
            previous_unit = point.unit_price
        else:
            continue
        delta_unit = current_unit - previous_unit
        delta_pct = float((delta_unit / previous_unit * 100).quantize(Decimal("0.1"))) if previous_unit > 0 else None
        delta_total += delta_unit * item.quantity
        compared += 1
        items_out.append(
            {
                "ordinal": item.ordinal,
                "previous_unit_price": str(previous_unit.quantize(Decimal("0.01"))),
                "previous_on": point.observed_on.isoformat(),
                "previous_store_name": store_name,
                "delta_unit": str(delta_unit.quantize(Decimal("0.01"))),
                "delta_pct": delta_pct,
                "comparable": True,
            }
        )
    if placed == 0:
        return None
    return {
        "compared_items": compared,
        "total_items": len(receipt.items),
        "delta_total": _money(delta_total),
        "items": items_out,
    }


async def refresh_variations(session: AsyncSession, receipt: Receipt) -> None:
    for link in receipt.links:
        link.variation_summary = await compute_variation(session, receipt, link.workspace_id)
    await session.flush()


# ---------------------------------------------------------------------------
# product-centred answers
# ---------------------------------------------------------------------------
def _point_out(point: PricePoint, store: Optional[Store], mine: bool) -> dict[str, Any]:
    return {
        "observed_on": point.observed_on.isoformat(),
        "store_id": str(point.store_id),
        "store_name": (store.trade_name or store.legal_name) if store else None,
        "unit": point.unit,
        "quantity": str(point.quantity),
        "unit_price": str(point.unit_price),
        "normalized_price": str(point.normalized_price) if point.normalized_price is not None else None,
        "base_unit": point.base_unit,
        "is_outlier": point.is_outlier,
        "source": point.source,
        "mine": mine,
    }


async def product_history(
    session: AsyncSession, product: Product, workspace_id: uuid.UUID, *, days: int = 365, limit: int = 500
) -> list[dict[str, Any]]:
    since = date.today() - timedelta(days=days)
    mine_ids = set(
        (
            await session.execute(
                select(PricePoint.id)
                .join(ReceiptLink, ReceiptLink.receipt_id == PricePoint.receipt_id)
                .where(
                    PricePoint.product_id == product.id,
                    ReceiptLink.workspace_id == workspace_id,
                    ReceiptLink.not_my_purchase.is_(False),
                )
            )
        ).scalars().all()
    )
    rows = (
        await session.execute(
            select(PricePoint)
            .options(selectinload(PricePoint.store))
            .where(PricePoint.product_id == product.id, PricePoint.voided_at.is_(None), PricePoint.observed_on >= since)
            .order_by(PricePoint.observed_on.asc(), PricePoint.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    return [_point_out(p, p.store, p.id in mine_ids) for p in rows]


async def best_price(session: AsyncSession, product: Product, *, days: int = BEST_PRICE_WINDOW_DAYS) -> Optional[dict[str, Any]]:
    """Lowest comparable observation per store in the window, with the
    date — an observed price is not a current price."""
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(PricePoint)
            .options(selectinload(PricePoint.store))
            .where(
                PricePoint.product_id == product.id,
                PricePoint.voided_at.is_(None),
                PricePoint.is_outlier.is_(False),
                PricePoint.comparable.is_(True),
                PricePoint.observed_on >= since,
            )
        )
    ).scalars().all()
    if not rows:
        return None
    key = lambda p: (p.normalized_price if p.normalized_price is not None else p.unit_price)  # noqa: E731
    best = min(rows, key=key)
    return _point_out(best, best.store, False)


async def last_paid(session: AsyncSession, product: Product, workspace_id: uuid.UUID) -> Optional[dict[str, Any]]:
    row = (
        await session.execute(
            select(PricePoint)
            .options(selectinload(PricePoint.store))
            .join(ReceiptLink, ReceiptLink.receipt_id == PricePoint.receipt_id)
            .where(
                PricePoint.product_id == product.id,
                PricePoint.voided_at.is_(None),
                ReceiptLink.workspace_id == workspace_id,
                ReceiptLink.not_my_purchase.is_(False),
            )
            .order_by(PricePoint.observed_on.desc(), PricePoint.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _point_out(row, row.store, True) if row else None


async def recent_items_without_gtin(
    session: AsyncSession, workspace_id: uuid.UUID, *, limit: int = 50
) -> list[tuple[ReceiptItem, Receipt]]:
    """For "you already bought this? pick the line": the workspace's recent
    lines whose product is still chain-scoped."""
    rows = (
        await session.execute(
            select(ReceiptItem, Receipt)
            .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
            .join(ReceiptLink, ReceiptLink.receipt_id == Receipt.id)
            .join(Product, Product.id == ReceiptItem.product_id)
            .where(ReceiptLink.workspace_id == workspace_id, Receipt.status == "authorized", Product.gtin.is_(None))
            .order_by(Receipt.issued_on.desc().nulls_last(), ReceiptItem.ordinal.asc())
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]
