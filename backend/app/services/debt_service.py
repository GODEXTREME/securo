"""Debt payoff planner (snowball / avalanche).

Reads the workspace's debts (credit cards and any overdrawn/negative-balance
accounts), then simulates month-by-month payoff under both strategies given an
extra monthly payment on top of the minimums. Returns payoff time, total
interest and the per-debt order for each strategy so the UI can compare them.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import dashboard_service

DEBT_TYPES = ("credit_card",)
MAX_MONTHS = 600  # 50-year guard against never-amortizing inputs
DEFAULT_APR = 24.0  # assumed when an account has no APR set
MIN_PAYMENT_PCT = Decimal("0.02")  # 2% of balance floor when none is known


async def get_debt_accounts(session: AsyncSession, workspace_id: uuid.UUID) -> list[dict]:
    accounts = await dashboard_service._get_open_accounts(session, workspace_id)
    debts: list[dict] = []
    for acc in accounts:
        bal = acc.balance if acc.balance is not None else Decimal("0")
        # Debt = credit card with an owed balance, or a non-credit account overdrawn.
        owed = Decimal("0")
        if acc.type == "credit_card" and bal > 0:
            owed = bal
        elif acc.type not in ("credit_card", "investment") and bal < 0:
            owed = abs(bal)
        if owed <= 0:
            continue
        min_pay = acc.minimum_payment if acc.minimum_payment else (owed * MIN_PAYMENT_PCT)
        debts.append({
            "id": str(acc.id),
            "name": acc.display_name or acc.name,
            "balance": float(owed),
            "apr": float(acc.apr) if acc.apr is not None else DEFAULT_APR,
            "min_payment": round(float(min_pay), 2),
            "currency": acc.currency,
        })
    debts.sort(key=lambda d: d["balance"], reverse=True)
    return debts


def _simulate(debts: list[dict], extra_payment: float, strategy: str) -> dict:
    """Simulate payoff. ``debts`` items need name/balance/apr/min_payment."""
    # Working copies.
    work = [
        {"name": d["name"], "balance": Decimal(str(d["balance"])),
         "rate": Decimal(str(d["apr"])) / Decimal("1200"),
         "min": Decimal(str(d["min_payment"]))}
        for d in debts if float(d["balance"]) > 0
    ]
    if not work:
        return {"months": 0, "total_interest": 0.0, "payoff_date": date.today().isoformat(), "order": []}

    # Payoff priority.
    if strategy == "avalanche":
        order_idx = sorted(range(len(work)), key=lambda i: work[i]["rate"], reverse=True)
    else:  # snowball
        order_idx = sorted(range(len(work)), key=lambda i: work[i]["balance"])

    extra = Decimal(str(extra_payment))
    total_interest = Decimal("0")
    months = 0
    payoff_order: list[str] = []

    while any(d["balance"] > Decimal("0.01") for d in work) and months < MAX_MONTHS:
        months += 1
        # Accrue interest.
        for d in work:
            if d["balance"] > 0:
                total_interest += (d["balance"] * d["rate"]).quantize(Decimal("0.01"))
                d["balance"] += (d["balance"] * d["rate"]).quantize(Decimal("0.01"))

        # Budget for the month = sum of minimums (on still-open debts) + extra.
        budget = extra + sum((d["min"] for d in work if d["balance"] > 0), Decimal("0"))

        # Pay minimums first.
        for d in work:
            if d["balance"] <= 0:
                continue
            pay = min(d["min"], d["balance"], budget)
            d["balance"] -= pay
            budget -= pay

        # Funnel remaining budget into the priority debt.
        for i in order_idx:
            if budget <= 0:
                break
            d = work[i]
            if d["balance"] <= 0:
                continue
            pay = min(budget, d["balance"])
            d["balance"] -= pay
            budget -= pay

        # Record any debts cleared this month.
        for i in order_idx:
            if work[i]["balance"] <= Decimal("0.01") and work[i]["name"] not in payoff_order:
                payoff_order.append(work[i]["name"])

    today = date.today()
    payoff_year = today.year + (today.month - 1 + months) // 12
    payoff_month = (today.month - 1 + months) % 12 + 1
    payoff = date(payoff_year, payoff_month, 1)

    return {
        "months": months,
        "total_interest": round(float(total_interest), 2),
        "payoff_date": payoff.isoformat(),
        "order": payoff_order,
        "amortized": months < MAX_MONTHS,
    }


async def plan(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    extra_payment: float = 0.0,
    overrides: list[dict] | None = None,
) -> dict:
    debts = overrides if overrides else await get_debt_accounts(session, workspace_id)
    debts = [d for d in debts if float(d.get("balance", 0)) > 0]
    total_balance = round(sum(float(d["balance"]) for d in debts), 2)
    total_min = round(sum(float(d["min_payment"]) for d in debts), 2)

    snowball = _simulate(debts, extra_payment, "snowball")
    avalanche = _simulate(debts, extra_payment, "avalanche")

    return {
        "debts": debts,
        "total_balance": total_balance,
        "total_minimum": total_min,
        "extra_payment": extra_payment,
        "snowball": snowball,
        "avalanche": avalanche,
        "recommended": "avalanche" if avalanche["total_interest"] <= snowball["total_interest"] else "snowball",
    }
