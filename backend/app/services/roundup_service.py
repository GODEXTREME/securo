"""Round-ups.

Sums the "spare change" from expenses over a period: each debit is rounded up
to the next whole unit and the difference (times an optional multiplier) is the
round-up. The frontend then sweeps the accumulated amount into a savings bucket
via the existing sinking-fund contribute endpoint.
"""
import math
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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


async def get_roundups(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID,
    months: int = 1, multiplier: int = 1,
) -> dict:
    user = await session.get(User, user_id)
    currency = user.primary_currency if user else get_settings().default_currency
    start = _shift_month(_first_of_month(date.today()), max(0, months - 1))
    amount = func.coalesce(Transaction.amount_primary, Transaction.amount)

    rows = await session.execute(
        select(func.abs(amount)).where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.is_ignored == False,
            Transaction.date >= start,
        )
    )
    total = Decimal("0")
    count = 0
    for (amt,) in rows.all():
        a = Decimal(str(amt or 0))
        if a <= 0:
            continue
        roundup = Decimal(str(math.ceil(a))) - a
        if roundup > 0:
            total += roundup
            count += 1

    total *= multiplier
    return {
        "currency": currency,
        "months": months,
        "multiplier": multiplier,
        "transaction_count": count,
        "roundup_total": float(total.quantize(Decimal("0.01"))),
    }
