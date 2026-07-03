"""Emergency-fund tracker.

One plan per workspace: a target in months of expenses and the amount set aside
(manual or a linked account's balance). The target value, progress and how many
months of spending are covered are computed from the workspace's recent average
monthly expenses.
"""
import math
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.emergency_fund import EmergencyFund
from app.models.transaction import Transaction
from app.schemas.emergency_fund import EmergencyFundRead, EmergencyFundUpdate
from app.services.account_service import get_account_name


async def _avg_monthly_expense(session: AsyncSession, workspace_id: uuid.UUID, months: int = 3) -> float:
    today = date.today()
    y = today.year + (today.month - 1 - (months - 1)) // 12
    m = (today.month - 1 - (months - 1)) % 12 + 1
    start = date(y, m, 1)
    amount = func.coalesce(Transaction.amount_primary, Transaction.amount)
    total = (await session.execute(
        select(func.sum(func.abs(amount))).where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.is_ignored == False,
            Transaction.date >= start,
        )
    )).scalar()
    return round(float(total or 0) / months, 2)


async def _get_or_create(session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> EmergencyFund:
    ef = (await session.execute(
        select(EmergencyFund).where(EmergencyFund.workspace_id == workspace_id)
    )).scalar_one_or_none()
    if ef is None:
        ef = EmergencyFund(user_id=user_id, workspace_id=workspace_id)
        session.add(ef)
        await session.commit()
        await session.refresh(ef)
    return ef


async def _to_read(session: AsyncSession, ef: EmergencyFund, currency: str) -> EmergencyFundRead:
    avg = await _avg_monthly_expense(session, ef.workspace_id)
    target = round(ef.target_months * avg, 2)

    account_name = None
    saved = float(ef.current_amount or 0)
    if ef.account_id:
        acc = await session.get(Account, ef.account_id)
        if acc:
            account_name = get_account_name(acc)
            saved = float(acc.balance or 0)

    progress = round(min(100.0, saved / target * 100), 1) if target > 0 else 0.0
    months_covered = round(saved / avg, 1) if avg > 0 else 0.0
    shortfall = round(max(0.0, target - saved), 2)
    contribution = float(ef.monthly_contribution) if ef.monthly_contribution else 0.0
    months_to_complete = math.ceil(shortfall / contribution) if contribution > 0 and shortfall > 0 else (0 if shortfall <= 0 else None)

    return EmergencyFundRead(
        target_months=ef.target_months,
        current_amount=float(ef.current_amount or 0),
        account_id=ef.account_id,
        account_name=account_name,
        monthly_contribution=contribution or None,
        currency=currency,
        avg_monthly_expense=avg,
        target_amount=target,
        saved_amount=round(saved, 2),
        progress_pct=progress,
        months_covered=months_covered,
        shortfall=shortfall,
        months_to_complete=months_to_complete,
    )


async def get(session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, currency: str) -> EmergencyFundRead:
    ef = await _get_or_create(session, workspace_id, user_id)
    return await _to_read(session, ef, currency)


async def update(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, currency: str, data: EmergencyFundUpdate
) -> EmergencyFundRead:
    ef = await _get_or_create(session, workspace_id, user_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(ef, key, value)
    await session.commit()
    await session.refresh(ef)
    return await _to_read(session, ef, currency)
