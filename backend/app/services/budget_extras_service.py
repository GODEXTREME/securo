"""Group-level budget rollup and a budget-adherence streak.

Both build on the existing per-category budget logic so behavior stays
consistent. ``group_summary`` aggregates category budgets and spending by
category group; ``get_streak`` counts consecutive past months where total
spending stayed within the total budget (a light gamification signal).
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.services import budget_service

STREAK_LOOKBACK = 24


def _shift_month(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


async def group_summary(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, month: Optional[date] = None
) -> dict:
    if not month:
        month = date.today().replace(day=1)
    rows = await budget_service.get_budget_vs_actual(session, workspace_id, user_id, month)

    groups: dict[str, dict] = {}
    for r in rows:
        key = str(r.group_id) if r.group_id else "ungrouped"
        name = r.group_name if r.group_id else None
        g = groups.setdefault(key, {"id": key, "name": name, "budget": 0.0, "actual": 0.0, "categories": 0})
        g["budget"] += float(r.budget_amount or 0)
        g["actual"] += float(r.actual_amount or 0)
        if r.budget_amount:
            g["categories"] += 1

    result: list[dict[str, Any]] = []
    for g in groups.values():
        if g["budget"] <= 0 and g["actual"] <= 0:
            continue
        pct = round(g["actual"] / g["budget"] * 100, 1) if g["budget"] > 0 else None
        result.append({
            "id": g["id"],
            "name": g["name"],
            "budget": round(g["budget"], 2),
            "actual": round(g["actual"], 2),
            "remaining": round(g["budget"] - g["actual"], 2),
            "percentage": pct,
            "categories": g["categories"],
            "over": g["budget"] > 0 and g["actual"] > g["budget"],
        })
    result.sort(key=lambda x: x["budget"], reverse=True)
    return {"month": month.isoformat(), "groups": result}


async def get_streak(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> dict:
    today = date.today()
    amount = func.coalesce(Transaction.amount_primary, Transaction.amount)

    streak = 0
    best = 0
    run = 0
    counting = True  # still consecutive back from the most recent completed month
    details: list[dict] = []
    # Walk backwards over completed months (skip the in-progress current month).
    for k in range(1, STREAK_LOOKBACK + 1):
        m_start = _shift_month(today.replace(day=1), k)
        m_end = _shift_month(today.replace(day=1), k - 1)
        budget_map = await budget_service._build_budget_map(session, workspace_id, m_start)
        total_budget = sum((amt for amt, _ in budget_map.values()), Decimal("0"))
        if total_budget <= 0:
            # No budget that month → can't judge; the active streak ends here.
            counting = False
            run = 0
            continue
        spent = await session.scalar(
            select(func.sum(func.abs(amount))).where(
                Transaction.workspace_id == workspace_id,
                Transaction.type == "debit",
                Transaction.is_ignored == False,
                Transaction.date >= m_start,
                Transaction.date < m_end,
            )
        ) or Decimal("0")
        within = Decimal(str(spent)) <= total_budget
        details.append({"month": m_start.strftime("%Y-%m"), "within": bool(within),
                        "budget": float(total_budget), "spent": float(spent)})
        if within:
            run += 1
            best = max(best, run)
            if counting:
                streak += 1
        else:
            counting = False
            run = 0

    return {"streak": streak, "best": best, "months": list(reversed(details))}
