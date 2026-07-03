"""Financial health score.

Combines four sub-scores into a 0–100 composite:
  * savings rate (last 3 months)
  * emergency-fund runway (liquid balance / average monthly expense)
  * debt burden (credit-card utilization + overall debt load)
  * cash-flow stability (income comfortably covering expenses)

Each sub-score is 0–100 with a short label; the composite is their weighted
average. Pure read.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.transaction import Transaction
from app.models.user import User
from app.services import dashboard_service
from app.services.fx_rate_service import convert

LIQUID_TYPES = ("checking", "savings", "wallet")


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _band(score: float) -> str:
    if score >= 80:
        return "excellent"
    if score >= 60:
        return "good"
    if score >= 40:
        return "fair"
    return "poor"


async def get_health_score(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> dict:
    user = await session.get(User, user_id)
    currency = user.primary_currency if user else get_settings().default_currency
    today = date.today()
    three_months_ago = today - timedelta(days=92)
    amount = func.coalesce(Transaction.amount_primary, Transaction.amount)

    _rate_cache: dict[str, Decimal] = {}

    async def to_primary(amt: Decimal, src: str) -> Decimal:
        if src == currency:
            return amt
        if src not in _rate_cache:
            one, _ = await convert(session, Decimal("1"), src, currency)
            _rate_cache[src] = one
        return amt * _rate_cache[src]

    # Income / expense over the last ~3 months.
    inc = await session.scalar(
        select(func.sum(func.abs(amount))).where(
            Transaction.workspace_id == workspace_id, Transaction.type == "credit",
            Transaction.is_ignored == False, Transaction.date >= three_months_ago,
        )
    ) or Decimal("0")
    exp = await session.scalar(
        select(func.sum(func.abs(amount))).where(
            Transaction.workspace_id == workspace_id, Transaction.type == "debit",
            Transaction.is_ignored == False, Transaction.date >= three_months_ago,
        )
    ) or Decimal("0")
    monthly_income = float(inc) / 3
    monthly_expense = float(exp) / 3

    # Balances by account type.
    accounts = await dashboard_service._get_open_accounts(session, workspace_id)
    liquid = Decimal("0")
    credit_owed = Decimal("0")
    credit_limit = Decimal("0")
    for acc in accounts:
        bal = acc.balance if acc.balance is not None else Decimal("0")
        if acc.type in LIQUID_TYPES:
            liquid += await to_primary(bal, acc.currency)
        elif acc.type == "credit_card":
            credit_owed += await to_primary(abs(bal), acc.currency)
            if acc.credit_limit:
                credit_limit += await to_primary(acc.credit_limit, acc.currency)

    liquid_f = float(liquid)

    # 1. Savings rate → 0% maps to 0, 25%+ maps to 100.
    savings_rate = (monthly_income - monthly_expense) / monthly_income * 100 if monthly_income > 0 else 0.0
    s_savings = _clamp(savings_rate / 25 * 100)

    # 2. Emergency fund runway (months) → 6+ months = 100.
    runway = liquid_f / monthly_expense if monthly_expense > 0 else (6 if liquid_f > 0 else 0)
    s_emergency = _clamp(runway / 6 * 100)

    # 3. Debt burden: credit utilization + owed vs annual income.
    utilization = float(credit_owed / credit_limit) if credit_limit > 0 else (0.0 if credit_owed == 0 else 1.0)
    annual_income = monthly_income * 12
    debt_to_income = float(credit_owed) / annual_income if annual_income > 0 else (0.0 if credit_owed == 0 else 1.0)
    s_debt = _clamp(100 - (utilization * 60) - min(debt_to_income, 1.0) * 40)

    # 4. Cash-flow stability: expenses as a share of income.
    ratio = monthly_expense / monthly_income if monthly_income > 0 else 1.5
    s_cashflow = _clamp((1.2 - ratio) / 1.2 * 100)

    components = [
        {"key": "savings_rate", "label": "Savings rate", "score": round(s_savings),
         "detail": f"{savings_rate:.0f}% of income saved"},
        {"key": "emergency_fund", "label": "Emergency fund", "score": round(s_emergency),
         "detail": f"{runway:.1f} months of expenses covered"},
        {"key": "debt_burden", "label": "Debt burden", "score": round(s_debt),
         "detail": f"{utilization * 100:.0f}% credit utilization"},
        {"key": "cash_flow", "label": "Cash flow", "score": round(s_cashflow),
         "detail": f"Spending {ratio * 100:.0f}% of income"},
    ]
    weights = {"savings_rate": 0.3, "emergency_fund": 0.3, "debt_burden": 0.2, "cash_flow": 0.2}
    composite = sum(c["score"] * weights[c["key"]] for c in components)

    return {
        "currency": currency,
        "score": round(composite),
        "band": _band(composite),
        "components": components,
        "monthly_income": round(monthly_income, 2),
        "monthly_expense": round(monthly_expense, 2),
        "liquid_balance": round(liquid_f, 2),
    }
