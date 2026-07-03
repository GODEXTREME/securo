"""Retirement / financial-independence (FIRE) projection.

Projects how a portfolio grows month by month from the current net worth plus a
recurring monthly contribution at an expected return, and finds when it reaches
the "FIRE number" — the nest egg that sustains a target annual spend at a chosen
safe-withdrawal rate (the 4% rule ⇒ 25× yearly expenses). The current net worth
is pulled from the workspace automatically, and a suggested monthly contribution
is derived from the last few months of income minus expenses.
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.services import report_service

MAX_MONTHS = 80 * 12  # 80-year guard


async def current_net_worth(
    session: AsyncSession, workspace_id: uuid.UUID, primary_currency: str
) -> float:
    point = await report_service._net_worth_at(
        session, workspace_id, date.today(), primary_currency
    )
    return float(point.value)


async def suggest_monthly_contribution(
    session: AsyncSession, workspace_id: uuid.UUID, months: int = 6
) -> float:
    """Average monthly (income − expense) over the last ``months`` full months."""
    today = date.today()
    start_year = today.year + (today.month - 1 - (months - 1)) // 12
    start_month = (today.month - 1 - (months - 1)) % 12 + 1
    start = date(start_year, start_month, 1)
    amount = func.coalesce(Transaction.amount_primary, Transaction.amount)
    rows = await session.execute(
        select(Transaction.type, func.sum(func.abs(amount)))
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.is_ignored == False,
            Transaction.date >= start,
            Transaction.type.in_(("credit", "debit")),
        )
        .group_by(Transaction.type)
    )
    income = expense = 0.0
    for tx_type, total in rows.all():
        if tx_type == "credit":
            income = float(total or 0)
        else:
            expense = float(total or 0)
    savings = (income - expense) / months
    return round(max(0.0, savings), 2)


def project(
    current_net_worth: float,
    monthly_contribution: float,
    annual_return: float,
    annual_expenses: float,
    withdrawal_rate: float = 4.0,
    current_age: int | None = None,
    currency: str = "USD",
) -> dict:
    nw = max(0.0, float(current_net_worth))
    contrib = max(0.0, float(monthly_contribution))
    withdrawal_rate = max(0.1, float(withdrawal_rate))
    fire_number = round(float(annual_expenses) / (withdrawal_rate / 100.0), 2) if annual_expenses > 0 else 0.0

    r_m = (1.0 + annual_return / 100.0) ** (1.0 / 12.0) - 1.0

    series: list[dict] = []
    today = date.today()
    balance = nw
    months = 0
    reached_month: int | None = None
    total_contributed = 0.0

    # Record year 0.
    series.append({"year": today.year, "month_index": 0, "value": round(balance, 2)})

    while months < MAX_MONTHS:
        months += 1
        balance = balance * (1.0 + r_m) + contrib
        total_contributed += contrib
        if reached_month is None and fire_number > 0 and balance >= fire_number:
            reached_month = months
        if months % 12 == 0:
            series.append({
                "year": today.year + months // 12,
                "month_index": months,
                "value": round(balance, 2),
            })
        # Stop a couple years past FIRE (or at the cap) so the chart has a tail.
        if reached_month is not None and months >= reached_month + 24:
            break

    years_to_fire = round(reached_month / 12, 1) if reached_month else None
    fire_date = None
    age_at_fire = None
    if reached_month:
        fy = today.year + (today.month - 1 + reached_month) // 12
        fm = (today.month - 1 + reached_month) % 12 + 1
        fire_date = date(fy, fm, 1).isoformat()
        if current_age is not None:
            age_at_fire = round(current_age + reached_month / 12, 1)

    progress_pct = round(min(100.0, nw / fire_number * 100), 1) if fire_number > 0 else 0.0
    monthly_income_at_fire = round(fire_number * (withdrawal_rate / 100.0) / 12.0, 2)

    return {
        "currency": currency,
        "current_net_worth": round(nw, 2),
        "monthly_contribution": round(contrib, 2),
        "annual_return": annual_return,
        "annual_expenses": round(float(annual_expenses), 2),
        "withdrawal_rate": withdrawal_rate,
        "fire_number": fire_number,
        "progress_pct": progress_pct,
        "years_to_fire": years_to_fire,
        "fire_date": fire_date,
        "age_at_fire": age_at_fire,
        "reached": reached_month is not None,
        "total_contributed": round(total_contributed, 2),
        "monthly_income_at_fire": monthly_income_at_fire,
        "series": series,
    }
