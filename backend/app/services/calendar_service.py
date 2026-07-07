"""Financial calendar.

Aggregates a month into per-day data the UI can render on a calendar grid:
  * daily actual income/expense totals (past & current, primary currency)
  * upcoming events: credit-card bills due and projected recurring
    transactions (income/expense)
"""
import calendar as _calmod
import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.category import Category
from app.models.credit_card_bill import CreditCardBill
from app.models.account import Account
from app.models.transaction import Transaction
from app.models.user import User
from app.services import dashboard_service


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    last = _calmod.monthrange(year, month)[1]
    return start, date(year, month, last)


async def get_calendar(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, year: int, month: int
) -> dict:
    user = await session.get(User, user_id)
    currency = user.primary_currency if user else get_settings().default_currency
    month_start, month_end = _month_bounds(year, month)
    amount = func.coalesce(Transaction.amount_primary, Transaction.amount)

    # Daily actual income/expense (bucketed in Python for portability).
    rows = await session.execute(
        select(Transaction.date, Transaction.type, func.abs(amount))
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.is_ignored == False,
            Transaction.date >= month_start,
            Transaction.date <= month_end,
        )
    )
    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0, "net": 0.0})
    for d, ttype, amt in rows.all():
        key = d.isoformat()
        val = float(amt or 0)
        if ttype == "credit":
            daily[key]["income"] += val
            daily[key]["net"] += val
        else:
            daily[key]["expense"] += val
            daily[key]["net"] -= val

    events: list[dict] = []

    # Credit-card bills due this month.
    bills = await session.execute(
        select(CreditCardBill, Account.name)
        .join(Account, CreditCardBill.account_id == Account.id)
        .where(
            CreditCardBill.workspace_id == workspace_id,
            CreditCardBill.due_date >= month_start,
            CreditCardBill.due_date <= month_end,
        )
    )
    for bill, account_name in bills.all():
        events.append({
            "date": bill.due_date.isoformat(),
            "kind": "bill",
            "title": account_name,
            "amount": -float(bill.total_amount),
            "currency": bill.currency,
        })

    # Projected recurring transactions (upcoming occurrences within the month).
    projections = await dashboard_service._get_recurring_projections(
        session, workspace_id, month_start, month_end
    )
    cat_ids = {p["category_id"] for p in projections if p["category_id"]}
    cat_names: dict[uuid.UUID, str] = {}
    if cat_ids:
        cres = await session.execute(select(Category.id, Category.name).where(Category.id.in_(cat_ids)))
        cat_names = {r[0]: r[1] for r in cres.all()}
    for p in projections:
        signed = float(p["amount"]) if p["type"] == "credit" else -float(p["amount"])
        events.append({
            "date": p["date"].isoformat(),
            "kind": "recurring_income" if p["type"] == "credit" else "recurring_expense",
            "title": cat_names.get(p["category_id"], "") or ("Income" if p["type"] == "credit" else "Expense"),
            "amount": signed,
            "currency": p["currency"],
        })

    # Projected credit-card installments not yet billed (upcoming parcels).
    inst_projections = await dashboard_service._get_installment_projections(
        session, workspace_id, month_start, month_end
    )
    for p in inst_projections:
        events.append({
            "date": p["date"].isoformat(),
            "kind": "installment",
            "title": f"{p['description']} {p['installment_number']}/{p['total_installments']}",
            "amount": -float(p["amount"]),
            "currency": p["currency"],
        })

    events.sort(key=lambda e: e["date"])
    month_income = round(sum(v["income"] for v in daily.values()), 2)
    month_expense = round(sum(v["expense"] for v in daily.values()), 2)

    return {
        "year": year,
        "month": month,
        "currency": currency,
        "daily": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in daily.items()},
        "events": events,
        "month_income": month_income,
        "month_expense": month_expense,
    }
