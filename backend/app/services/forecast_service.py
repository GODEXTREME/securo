"""Forward-looking cash-flow forecast.

Projects the liquid balance day by day over a horizon by starting from the
current liquid balance and applying recurring income/expenses and upcoming
credit-card bills. Surfaces the projected low point and any day the balance is
expected to go negative — the "act before the shortfall" signal.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.credit_card_bill import CreditCardBill
from app.models.user import User
from app.services import dashboard_service
from app.services.fx_rate_service import convert

LIQUID_TYPES = ("checking", "savings", "wallet")


async def _primary_currency(session: AsyncSession, user_id: uuid.UUID) -> str:
    user = await session.get(User, user_id)
    return user.primary_currency if user else get_settings().default_currency


async def get_forecast(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, days: int = 90
) -> dict:
    currency = await _primary_currency(session, user_id)
    today = date.today()
    horizon = today + timedelta(days=days)

    # Cache FX conversions per source currency.
    _rate_cache: dict[str, Decimal] = {}

    async def to_primary(amount: Decimal, src: str) -> Decimal:
        if src == currency:
            return amount
        if src not in _rate_cache:
            one, _ = await convert(session, Decimal("1"), src, currency)
            _rate_cache[src] = one
        return amount * _rate_cache[src]

    # Starting liquid balance.
    accounts = await dashboard_service._get_open_accounts(session, workspace_id)
    starting = Decimal("0")
    for acc in accounts:
        if acc.type not in LIQUID_TYPES:
            continue
        bal = acc.balance if acc.balance is not None else Decimal("0")
        starting += await to_primary(bal, acc.currency)

    # Daily net flow from recurring projections over the horizon.
    daily_flow: dict[date, Decimal] = {}
    projections = await dashboard_service._get_recurring_projections(
        session, workspace_id, today, horizon
    )
    for p in projections:
        d = p["date"]
        if d < today or d > horizon:
            continue
        amt = await to_primary(Decimal(str(p["amount"])), p["currency"])
        signed = amt if p["type"] == "credit" else -amt
        daily_flow[d] = daily_flow.get(d, Decimal("0")) + signed

    # Upcoming credit-card bills as outflows on their due date.
    bills = await session.execute(
        select(CreditCardBill).where(
            CreditCardBill.workspace_id == workspace_id,
            CreditCardBill.due_date >= today,
            CreditCardBill.due_date <= horizon,
        )
    )
    for bill in bills.scalars().all():
        amt = await to_primary(bill.total_amount, bill.currency)
        daily_flow[bill.due_date] = daily_flow.get(bill.due_date, Decimal("0")) - amt

    # Build cumulative series.
    series: list[dict] = []
    running = starting
    lowest = {"date": today.isoformat(), "balance": float(starting)}
    shortfalls: list[dict] = []
    d = today
    while d <= horizon:
        running += daily_flow.get(d, Decimal("0"))
        bal = float(running)
        series.append({"date": d.isoformat(), "balance": round(bal, 2)})
        if bal < lowest["balance"]:
            lowest = {"date": d.isoformat(), "balance": round(bal, 2)}
        if bal < 0:
            shortfalls.append({"date": d.isoformat(), "balance": round(bal, 2)})
        d += timedelta(days=1)

    return {
        "currency": currency,
        "days": days,
        "starting_balance": round(float(starting), 2),
        "ending_balance": series[-1]["balance"] if series else round(float(starting), 2),
        "lowest": lowest,
        "first_shortfall": shortfalls[0] if shortfalls else None,
        "shortfall_days": len(shortfalls),
        "series": series,
    }
