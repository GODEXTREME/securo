"""Advanced reporting: merchant breakdown, category trends over time and
period-over-period comparison. Self-contained (does not touch the core
report_service) so the existing reports stay untouched. All amounts are in the
user's primary currency via ``amount_primary`` when available.
"""
import uuid
from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _shift_month(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


async def _currency(session: AsyncSession, user_id: uuid.UUID) -> str:
    user = await session.get(User, user_id)
    return user.primary_currency if user else get_settings().default_currency


def _amount():
    return func.coalesce(Transaction.amount_primary, Transaction.amount)


async def merchant_breakdown(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID,
    months: int = 3, limit: int = 20, category_id: Optional[uuid.UUID] = None,
) -> dict:
    currency = await _currency(session, user_id)
    start = _shift_month(_first_of_month(date.today()), months - 1)
    amount = _amount()
    stmt = (
        select(
            func.coalesce(Transaction.payee, Transaction.description).label("merchant"),
            func.sum(func.abs(amount)),
            func.count(Transaction.id),
        )
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.is_ignored == False,
            Transaction.date >= start,
        )
    )
    if category_id:
        stmt = stmt.where(Transaction.category_id == category_id)
    stmt = stmt.group_by("merchant").order_by(func.sum(func.abs(amount)).desc()).limit(limit)
    rows = (await session.execute(stmt)).all()
    merchants = [
        {
            "merchant": (r[0] or "?")[:80],
            "total": round(float(r[1] or 0), 2),
            "count": r[2],
            "average": round(float(r[1] or 0) / r[2], 2) if r[2] else 0.0,
        }
        for r in rows
    ]
    return {"currency": currency, "months": months, "merchants": merchants}


async def category_trends(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, months: int = 6,
) -> dict:
    currency = await _currency(session, user_id)
    today = date.today()
    start = _shift_month(_first_of_month(today), months - 1)
    amount = _amount()
    rows = await session.execute(
        select(Transaction.date, Transaction.category_id, func.abs(amount))
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.is_ignored == False,
            Transaction.date >= start,
        )
    )
    # month_key -> {cat_id: total}. Bucketed in Python for DB portability.
    per_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    cat_ids: set[uuid.UUID] = set()
    for d, cat_id, total in rows.all():
        if cat_id is None:
            continue
        mk = d.strftime("%Y-%m")
        per_month[mk][str(cat_id)] += float(total or 0)
        cat_ids.add(cat_id)

    names: dict[str, str] = {}
    colors: dict[str, str] = {}
    if cat_ids:
        cres = await session.execute(
            select(Category.id, Category.name, Category.color).where(Category.id.in_(list(cat_ids)))
        )
        for r in cres.all():
            names[str(r[0])] = r[1]
            colors[str(r[0])] = r[2]

    month_keys = [_shift_month(_first_of_month(today), k).strftime("%Y-%m")
                  for k in range(months - 1, -1, -1)]
    series = []
    for mk in month_keys:
        row = {"month": mk}
        row.update({cid: round(v, 2) for cid, v in per_month.get(mk, {}).items()})
        series.append(row)

    categories = [
        {"id": cid, "name": names.get(cid, "Uncategorized"), "color": colors.get(cid)}
        for cid in {c for mk in month_keys for c in per_month.get(mk, {})}
    ]
    return {"currency": currency, "months": month_keys, "categories": categories, "series": series}


async def period_comparison(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, months: int = 1,
) -> dict:
    """Compare the last ``months`` window against the preceding one, by category."""
    currency = await _currency(session, user_id)
    today = date.today()
    cur_start = _shift_month(_first_of_month(today), months - 1)
    prev_start = _shift_month(cur_start, months)
    prev_end = cur_start
    amount = _amount()

    async def totals(start: date, end: Optional[date]) -> dict[str, float]:
        stmt = (
            select(Transaction.category_id, func.sum(func.abs(amount)))
            .where(
                Transaction.workspace_id == workspace_id,
                Transaction.type == "debit",
                Transaction.is_ignored == False,
                Transaction.date >= start,
            )
            .group_by(Transaction.category_id)
        )
        if end is not None:
            stmt = stmt.where(Transaction.date < end)
        return {str(r[0]): float(r[1] or 0) for r in (await session.execute(stmt)).all() if r[0]}

    cur = await totals(cur_start, None)
    prev = await totals(prev_start, prev_end)

    all_ids = set(cur) | set(prev)
    names: dict[str, str] = {}
    if all_ids:
        cres = await session.execute(
            select(Category.id, Category.name).where(
                Category.id.in_([uuid.UUID(i) for i in all_ids])
            )
        )
        names = {str(r[0]): r[1] for r in cres.all()}

    rows = []
    for cid in all_ids:
        c = cur.get(cid, 0.0)
        p = prev.get(cid, 0.0)
        rows.append({
            "category": names.get(cid, "Uncategorized"),
            "current": round(c, 2),
            "previous": round(p, 2),
            "change": round(c - p, 2),
            "change_pct": round((c - p) / p * 100, 1) if p > 0 else None,
        })
    rows.sort(key=lambda r: abs(r["change"]), reverse=True)
    return {
        "currency": currency,
        "months": months,
        "current_total": round(sum(cur.values()), 2),
        "previous_total": round(sum(prev.values()), 2),
        "rows": rows,
    }
