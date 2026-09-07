"""What the receipts add up to over a window.

The numbers a person actually wants once a few notes are in: what was
spent, what the repeated items cost compared with last time, which
products moved the most, and where the money went.

Aggregated in Python rather than in SQL. The variation lives in a JSON
column whose operators differ between Postgres and the SQLite the tests
run on, and the volume is one workspace's notes over a window — a page
of rows, not a report. Portability is worth more here than a query.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.receipt import Receipt, ReceiptItem, ReceiptLink

ZERO = Decimal("0")

#: How many products the panel names. Enough to see a pattern, few enough
#: to read at a glance.
TOP_MOVERS = 5
TOP_STORES = 5


@dataclass
class Mover:
    """A product whose unit price moved, and by how much."""
    product_id: Optional[uuid.UUID]
    name: str
    delta_unit: Decimal
    delta_pct: Optional[float]
    store_name: Optional[str]
    observed_on: Optional[date]


@dataclass
class StoreSpend:
    store_id: Optional[uuid.UUID]
    name: str
    total: Decimal
    receipts: int


@dataclass
class Summary:
    since: date
    until: date
    receipts: int = 0
    total_spent: Decimal = ZERO
    #: Lines that had a previous price to compare against.
    compared_items: int = 0
    #: Positive means the repeated items cost more than they did last time.
    delta_total: Decimal = ZERO
    movers: list[Mover] = field(default_factory=list)
    stores: list[StoreSpend] = field(default_factory=list)


def _decimal(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw))
    except (TypeError, ValueError):
        return ZERO


async def summary(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    days: int = 90,
    today: Optional[date] = None,
) -> Summary:
    """The window ends today and reaches `days` back. Notes marked "not my
    purchase" are left out of every number: they are on the instance
    because someone scanned them, not because this workspace bought them.
    """
    until = today or date.today()
    since = until - timedelta(days=days)
    result = await session.execute(
        select(ReceiptLink)
        .where(ReceiptLink.workspace_id == workspace_id, ReceiptLink.not_my_purchase.is_(False))
        .options(
            selectinload(ReceiptLink.receipt).selectinload(Receipt.items).selectinload(ReceiptItem.product),
            selectinload(ReceiptLink.receipt).selectinload(Receipt.store),
        )
    )

    out = Summary(since=since, until=until)
    stores: dict[Optional[uuid.UUID], StoreSpend] = {}
    movers: list[Mover] = []

    for link in result.scalars().all():
        receipt = link.receipt
        if receipt.status != "authorized":
            continue
        on = receipt.issued_on or receipt.first_scanned_at.date()
        if not (since <= on <= until):
            continue

        out.receipts += 1
        if receipt.total is not None:
            out.total_spent += Decimal(receipt.total)

        name = (
            (receipt.store.trade_name or receipt.store.legal_name)
            if receipt.store is not None
            else ""
        )
        key = receipt.store.id if receipt.store is not None else None
        spend = stores.get(key)
        if spend is None:
            spend = StoreSpend(store_id=key, name=name, total=ZERO, receipts=0)
            stores[key] = spend
        spend.total += Decimal(receipt.total) if receipt.total is not None else ZERO
        spend.receipts += 1

        variation = link.variation_summary
        if not isinstance(variation, dict):
            continue
        out.compared_items += int(variation.get("compared_items") or 0)
        out.delta_total += _decimal(variation.get("delta_total"))

        by_ordinal = {item.ordinal: item for item in receipt.items}
        for entry in variation.get("items") or []:
            item = by_ordinal.get(entry.get("ordinal"))
            if item is None:
                continue
            delta = _decimal(entry.get("delta_unit"))
            if delta == ZERO:
                continue
            movers.append(
                Mover(
                    product_id=item.product_id,
                    # The catalogue's name where there is one; the till's
                    # line when the product is still unnamed.
                    name=(item.product.name if item.product else None) or item.description,
                    delta_unit=delta,
                    delta_pct=entry.get("delta_pct"),
                    store_name=name or None,
                    observed_on=on,
                )
            )

    # Biggest movement first, whichever way it went: a fall is as much
    # news as a rise, and hiding it would make the panel a complaint.
    movers.sort(key=lambda mover: abs(mover.delta_unit), reverse=True)
    out.movers = movers[:TOP_MOVERS]
    out.stores = sorted(stores.values(), key=lambda spend: spend.total, reverse=True)[:TOP_STORES]
    return out
