"""Advanced reporting: merchant breakdown, category trends over time and
period-over-period comparison. Self-contained (does not touch the core
report_service) so the existing reports stay untouched. All amounts are in the
user's primary currency via ``amount_primary`` when available.
"""
import uuid
from calendar import monthrange as _monthrange
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.category import Category
from app.models.category_group import CategoryGroup
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


def _range_start(months: int, period: Optional[str]) -> date:
    """Month-aligned range start. period='ytd' → Jan 1; else the first day of
    (current month - (months-1)). months=1 → the current month only."""
    today = date.today()
    if period == "ytd":
        return date(today.year, 1, 1)
    return _shift_month(_first_of_month(today), max(0, months - 1))


async def category_breakdown(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    months: int = 1,
    period: Optional[str] = None,
    account_ids: Optional[list[uuid.UUID]] = None,
    flow: str = "expense",
    year: Optional[int] = None,
    month: Optional[int] = None,
    date_basis: Optional[str] = None,
) -> dict:
    """Spending (or income) for a two-ring pie chart.

    Returns ``groups`` (inner ring: main categories — a category's group, an
    ungrouped category on its own, or "Uncategorized") and ``children`` (outer
    ring: the leaf categories, each pointing at its parent group). ``slices`` is
    kept as an alias of ``groups`` for backward compatibility.

    When ``year`` and ``month`` are given, the window is exactly that calendar
    month (used by the month stepper); otherwise it's the last ``months``/period.
    """
    currency = await _currency(session, user_id)
    amount = _amount()
    tx_type = "credit" if flow == "income" else "debit"

    if year and month:
        start = date(year, month, 1)
        end = date(year, month, _monthrange(year, month)[1])
    else:
        start = _range_start(months, period)
        end = date.today()

    # By default bucket by purchase date; date_basis="effective" buckets by the
    # credit-card bill/due date (fatura) so a card view lines up with the invoice.
    from app.services._query_filters import reporting_date_col
    date_col = reporting_date_col("accrual") if date_basis == "effective" else Transaction.date
    conds = [
        Transaction.workspace_id == workspace_id,
        Transaction.type == tx_type,
        Transaction.is_ignored == False,
        date_col >= start,
        date_col <= end,
    ]
    if account_ids is not None:
        conds.append(Transaction.account_id.in_(account_ids))

    # Per-category totals (null category_id groups the uncategorized ones).
    rows = await session.execute(
        select(Transaction.category_id, func.sum(func.abs(amount)))
        .where(*conds)
        .group_by(Transaction.category_id)
    )
    per_cat: dict[Optional[uuid.UUID], float] = {r[0]: float(r[1] or 0) for r in rows.all()}

    # Resolve each category to (group_id, name, color) and groups to (name, color).
    cat_ids = [cid for cid in per_cat if cid is not None]
    cat_info: dict[uuid.UUID, tuple[Optional[uuid.UUID], str, str]] = {}
    if cat_ids:
        cres = await session.execute(
            select(Category.id, Category.group_id, Category.name, Category.color).where(Category.id.in_(cat_ids))
        )
        cat_info = {r[0]: (r[1], r[2], r[3]) for r in cres.all()}
    group_ids = {info[0] for info in cat_info.values() if info[0]}
    group_info: dict[uuid.UUID, tuple[str, str]] = {}
    if group_ids:
        gres = await session.execute(
            select(CategoryGroup.id, CategoryGroup.name, CategoryGroup.color).where(CategoryGroup.id.in_(group_ids))
        )
        group_info = {r[0]: (r[1], r[2]) for r in gres.all()}

    # Build the inner ring (groups) and outer ring (leaf categories).
    groups: dict[str, dict] = {}
    children: list[dict] = []
    for cid, total in per_cat.items():
        if total <= 0:
            continue
        if cid is None:
            parent_key, parent_name, parent_color, is_group = "uncategorized", None, "#94A3B8", False
            child = {"id": "uncategorized", "name": None, "color": "#94A3B8", "uncategorized": True}
        else:
            group_id, cat_name, cat_color = cat_info.get(cid, (None, "?", "#6B7280"))
            if group_id and group_id in group_info:
                gname, gcolor = group_info[group_id]
                parent_key, parent_name, parent_color, is_group = f"g:{group_id}", gname, gcolor, True
            else:
                parent_key, parent_name, parent_color, is_group = f"c:{cid}", cat_name, cat_color, False
            child = {"id": f"c:{cid}", "name": cat_name, "color": cat_color, "uncategorized": False}

        slot = groups.setdefault(parent_key, {
            "id": parent_key, "name": parent_name, "color": parent_color, "total": 0.0,
            "is_group": is_group, "uncategorized": cid is None,
        })
        slot["total"] += total
        children.append({**child, "total": total, "parent": parent_key})

    grand = round(sum(g["total"] for g in groups.values()), 2)

    def _finish(items: list[dict]) -> list[dict]:
        for it in items:
            it["total"] = round(it["total"], 2)
            it["percentage"] = round(it["total"] / grand * 100, 1) if grand > 0 else 0.0
        return items

    group_list = _finish(sorted(groups.values(), key=lambda s: s["total"], reverse=True))
    order = {g["id"]: i for i, g in enumerate(group_list)}
    # Order children by their parent group's rank, then by size, so the outer
    # ring lines up with the inner ring.
    child_list = _finish(sorted(children, key=lambda c: (order.get(c["parent"], 999), -c["total"])))

    return {
        "currency": currency,
        "flow": flow,
        "total": grand,
        "groups": group_list,
        "children": child_list,
        "slices": group_list,  # backward-compat alias
    }


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

    rows: list[dict[str, Any]] = []
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
