"""Spending insights and anomaly detection.

Derives a set of human-readable insights from the last few months of
transactions: month-over-month category movers, statistical anomalies
(a category's spend well above its recent average), the savings-rate trend,
and the top merchants of the current month. Pure read.
"""
import uuid
from collections import defaultdict
from datetime import date
from statistics import mean, pstdev

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User

MONTHS_BACK = 6


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _shift_month(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


async def _primary_currency(session: AsyncSession, user_id: uuid.UUID) -> str:
    user = await session.get(User, user_id)
    return user.primary_currency if user else get_settings().default_currency


async def get_insights(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> dict:
    currency = await _primary_currency(session, user_id)
    today = date.today()
    start = _shift_month(_first_of_month(today), MONTHS_BACK - 1)
    amount = func.coalesce(Transaction.amount_primary, Transaction.amount)

    # Per-month, per-category expense totals. Bucketed in Python (over raw rows)
    # so the query is portable across Postgres and SQLite (no date_trunc).
    rows = await session.execute(
        select(Transaction.date, Transaction.category_id, func.abs(amount))
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.is_ignored == False,
            Transaction.date >= start,
        )
    )
    # cat -> {month_key: total}
    by_cat: dict[uuid.UUID, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for d, cat_id, total in rows.all():
        if cat_id is None:
            continue
        by_cat[cat_id][_month_key(d)] += float(total or 0)

    cat_names: dict[uuid.UUID, str] = {}
    if by_cat:
        cres = await session.execute(
            select(Category.id, Category.name).where(Category.id.in_(list(by_cat.keys())))
        )
        cat_names = {r[0]: r[1] for r in cres.all()}

    cur_key = _month_key(today)
    prev_key = _month_key(_shift_month(_first_of_month(today), 1))

    insights: list[dict] = []
    movers: list[dict] = []
    for cat_id, months in by_cat.items():
        name = cat_names.get(cat_id, "Uncategorized")
        cur = months.get(cur_key, 0.0)
        prev = months.get(prev_key, 0.0)
        history = [months.get(_month_key(_shift_month(_first_of_month(today), k)), 0.0)
                   for k in range(1, MONTHS_BACK)]
        history = [h for h in history if h > 0]

        # Month-over-month mover
        if prev > 0 and cur > 0:
            delta = (cur - prev) / prev
            if abs(delta) >= 0.25 and abs(cur - prev) >= 20:
                movers.append({
                    "category": name, "direction": "up" if delta > 0 else "down",
                    "current": round(cur, 2), "previous": round(prev, 2),
                    "change_pct": round(delta * 100, 0),
                })

        # Anomaly: current month well above the recent mean.
        if len(history) >= 3 and cur > 0:
            mu = mean(history)
            sigma = pstdev(history) or (mu * 0.2)
            if mu > 0 and cur > mu + 2 * sigma and cur - mu >= 30:
                insights.append({
                    "type": "anomaly", "severity": "warning", "category": name,
                    "title": f"Unusual spending in {name}",
                    "detail": f"You spent {cur:.0f} {currency} in {name} this month, "
                              f"well above your ~{mu:.0f} average.",
                    "value": round(cur, 2),
                })

    movers.sort(key=lambda x: abs(x["current"] - x["previous"]), reverse=True)

    # Savings rate per month (bucketed in Python for DB portability).
    inc_exp = await session.execute(
        select(Transaction.date, Transaction.type, func.abs(amount))
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.is_ignored == False,
            Transaction.date >= start,
        )
    )
    income: dict[str, float] = defaultdict(float)
    expense: dict[str, float] = defaultdict(float)
    for d, ttype, total in inc_exp.all():
        key = _month_key(d)
        if ttype == "credit":
            income[key] += float(total or 0)
        else:
            expense[key] += float(total or 0)

    savings_series = []
    for k in range(MONTHS_BACK - 1, -1, -1):
        mk = _month_key(_shift_month(_first_of_month(today), k))
        inc = income.get(mk, 0.0)
        exp = expense.get(mk, 0.0)
        rate = round((inc - exp) / inc * 100, 1) if inc > 0 else 0.0
        savings_series.append({"month": mk, "income": round(inc, 2), "expense": round(exp, 2), "savings_rate": rate})

    if len(savings_series) >= 2:
        cur_rate = savings_series[-1]["savings_rate"]
        prev_rate = savings_series[-2]["savings_rate"]
        if cur_rate < prev_rate - 10:
            insights.append({
                "type": "savings", "severity": "warning", "category": None,
                "title": "Savings rate dropped",
                "detail": f"Your savings rate fell to {cur_rate:.0f}% from {prev_rate:.0f}% last month.",
                "value": cur_rate,
            })
        elif cur_rate > prev_rate + 10:
            insights.append({
                "type": "savings", "severity": "positive", "category": None,
                "title": "Savings rate improved",
                "detail": f"Your savings rate rose to {cur_rate:.0f}% from {prev_rate:.0f}% last month.",
                "value": cur_rate,
            })

    # Top merchants this month.
    cur_start = _first_of_month(today)
    merch = await session.execute(
        select(
            func.coalesce(Transaction.payee, Transaction.description),
            func.sum(func.abs(amount)),
            func.count(Transaction.id),
        )
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.is_ignored == False,
            Transaction.date >= cur_start,
        )
        .group_by(func.coalesce(Transaction.payee, Transaction.description))
        .order_by(func.sum(func.abs(amount)).desc())
        .limit(5)
    )
    top_merchants = [
        {"name": (r[0] or "?")[:60], "total": round(float(r[1] or 0), 2), "count": r[2]}
        for r in merch.all()
    ]

    return {
        "currency": currency,
        "insights": insights,
        "movers": movers[:6],
        "savings_series": savings_series,
        "top_merchants": top_merchants,
    }
