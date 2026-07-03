"""Subscription detection.

Groups posted debit transactions by merchant (payee, else a normalized
description) and looks for a regular cadence. Any merchant charged at a
consistent weekly / monthly / quarterly / yearly interval at least
``MIN_OCCURRENCES`` times is surfaced as a subscription, with its typical
amount, next expected charge and a flag when the latest amount jumped.

Pure read — no persistence. The frontend can hide false positives client-side.
"""
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction

MIN_OCCURRENCES = 3
LOOKBACK_DAYS = 400  # a bit over a year so yearly subscriptions get 2 hits

# interval (days) → (frequency label, tolerance days)
_FREQUENCIES = [
    (7, "weekly", 3),
    (14, "biweekly", 4),
    (30, "monthly", 7),
    (91, "quarterly", 12),
    (365, "yearly", 20),
]

_MONTHLY_FACTOR = {
    "weekly": Decimal("4.345"),
    "biweekly": Decimal("2.173"),
    "monthly": Decimal("1"),
    "quarterly": Decimal("0.333"),
    "yearly": Decimal("0.0833"),
}


def _normalize(text: str) -> str:
    t = text.lower()
    t = re.sub(r"\d+", "", t)  # drop numbers (invoice ids, dates)
    t = re.sub(r"[^a-zà-ÿ ]", " ", t)  # keep letters/accents
    t = re.sub(r"\s+", " ", t).strip()
    return t[:60]


def _classify(intervals: list[int]) -> Optional[tuple[str, int]]:
    if not intervals:
        return None
    m = median(intervals)
    for days, label, tol in _FREQUENCIES:
        if abs(m - days) <= tol:
            return label, days
    return None


async def detect_subscriptions(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[dict]:
    since = date.today() - timedelta(days=LOOKBACK_DAYS)
    result = await session.execute(
        select(Transaction).where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.is_ignored == False,
            Transaction.date >= since,
            Transaction.status == "posted",
        )
    )
    txns = list(result.scalars().all())

    groups: dict[str, list[Transaction]] = {}
    for tx in txns:
        key = tx.payee.strip().lower() if tx.payee else _normalize(tx.description)
        if not key:
            continue
        groups.setdefault(key, []).append(tx)

    subscriptions: list[dict] = []
    for key, items in groups.items():
        if len(items) < MIN_OCCURRENCES:
            continue
        items.sort(key=lambda t: t.date)
        intervals = [(items[i].date - items[i - 1].date).days for i in range(1, len(items))]
        classified = _classify(intervals)
        if not classified:
            continue
        frequency, period_days = classified

        amounts = [abs(t.amount) for t in items]
        typical = Decimal(str(median(amounts)))
        last = items[-1]
        last_amount = abs(last.amount)
        # Price-change flag: latest charge deviates > 10% from the typical amount.
        price_change = typical > 0 and abs(last_amount - typical) / typical > Decimal("0.10")

        next_date = last.date + timedelta(days=period_days)
        monthly_cost = typical * _MONTHLY_FACTOR.get(frequency, Decimal("1"))

        subscriptions.append({
            "key": key,
            "name": last.payee or last.description[:60],
            "frequency": frequency,
            "typical_amount": float(typical),
            "last_amount": float(last_amount),
            "currency": last.currency,
            "monthly_cost": float(monthly_cost.quantize(Decimal("0.01"))),
            "yearly_cost": float((monthly_cost * 12).quantize(Decimal("0.01"))),
            "occurrences": len(items),
            "last_date": last.date.isoformat(),
            "next_date": next_date.isoformat(),
            "price_change": bool(price_change),
            "category_id": str(last.category_id) if last.category_id else None,
        })

    subscriptions.sort(key=lambda s: s["monthly_cost"], reverse=True)
    return subscriptions


async def summarize(session: AsyncSession, workspace_id: uuid.UUID) -> dict:
    subs = await detect_subscriptions(session, workspace_id)
    monthly = sum(s["monthly_cost"] for s in subs)
    return {
        "count": len(subs),
        "monthly_total": round(monthly, 2),
        "yearly_total": round(monthly * 12, 2),
        "price_changes": sum(1 for s in subs if s["price_change"]),
        "subscriptions": subs,
    }
