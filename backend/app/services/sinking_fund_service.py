"""Sinking funds (savings buckets) — CRUD plus a contribute/withdraw action.

The suggested monthly contribution is derived from the remaining amount and the
number of whole months until the target date; a user-set monthly_contribution
overrides it.
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.sinking_fund import SinkingFund
from app.schemas.sinking_fund import SinkingFundCreate, SinkingFundRead, SinkingFundUpdate
from app.services.account_service import get_account_name


def _months_until(target: Optional[date]) -> Optional[int]:
    if not target:
        return None
    today = date.today()
    months = (target.year - today.year) * 12 + (target.month - today.month)
    return max(0, months)


async def _to_read(session: AsyncSession, fund: SinkingFund) -> SinkingFundRead:
    read = SinkingFundRead.model_validate(fund)
    target = float(fund.target_amount) or 0.0
    current = float(fund.current_amount)
    read.percentage = round(min(100.0, current / target * 100), 1) if target > 0 else 0.0

    remaining = max(0.0, target - current)
    months = _months_until(fund.target_date)
    read.months_remaining = months
    if fund.monthly_contribution is not None:
        read.suggested_monthly = float(fund.monthly_contribution)
    elif months and months > 0:
        read.suggested_monthly = round(remaining / months, 2)
    else:
        read.suggested_monthly = round(remaining, 2) if remaining > 0 else 0.0

    if fund.account_id:
        acc = await session.get(Account, fund.account_id)
        if acc:
            read.account_name = get_account_name(acc)
    return read


async def list_funds(
    session: AsyncSession, workspace_id: uuid.UUID, status: Optional[str] = None
) -> list[SinkingFundRead]:
    stmt = select(SinkingFund).where(SinkingFund.workspace_id == workspace_id)
    if status:
        stmt = stmt.where(SinkingFund.status == status)
    stmt = stmt.order_by(SinkingFund.position, SinkingFund.created_at)
    funds = list((await session.execute(stmt)).scalars().all())
    return [await _to_read(session, f) for f in funds]


async def get_fund(
    session: AsyncSession, fund_id: uuid.UUID, workspace_id: uuid.UUID
) -> Optional[SinkingFund]:
    fund = await session.get(SinkingFund, fund_id)
    if not fund or fund.workspace_id != workspace_id:
        return None
    return fund


async def create_fund(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, data: SinkingFundCreate
) -> SinkingFundRead:
    fund = SinkingFund(
        user_id=user_id,
        workspace_id=workspace_id,
        name=data.name,
        target_amount=data.target_amount,
        current_amount=data.current_amount,
        currency=data.currency,
        target_date=data.target_date,
        monthly_contribution=data.monthly_contribution,
        account_id=data.account_id,
        icon=data.icon,
        color=data.color,
    )
    session.add(fund)
    await session.commit()
    await session.refresh(fund)
    return await _to_read(session, fund)


async def update_fund(
    session: AsyncSession, fund_id: uuid.UUID, workspace_id: uuid.UUID, data: SinkingFundUpdate
) -> Optional[SinkingFundRead]:
    fund = await get_fund(session, fund_id, workspace_id)
    if not fund:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(fund, key, value)
    await session.commit()
    await session.refresh(fund)
    return await _to_read(session, fund)


async def contribute(
    session: AsyncSession, fund_id: uuid.UUID, workspace_id: uuid.UUID, amount: Decimal
) -> Optional[SinkingFundRead]:
    fund = await get_fund(session, fund_id, workspace_id)
    if not fund:
        return None
    fund.current_amount = (fund.current_amount or Decimal("0")) + amount
    if fund.current_amount < 0:
        fund.current_amount = Decimal("0")
    if fund.target_amount > 0 and fund.current_amount >= fund.target_amount:
        fund.status = "completed"
    elif fund.status == "completed":
        fund.status = "active"
    await session.commit()
    await session.refresh(fund)
    return await _to_read(session, fund)


async def delete_fund(
    session: AsyncSession, fund_id: uuid.UUID, workspace_id: uuid.UUID
) -> bool:
    fund = await get_fund(session, fund_id, workspace_id)
    if not fund:
        return False
    await session.delete(fund)
    await session.commit()
    return True


async def summary(session: AsyncSession, workspace_id: uuid.UUID) -> dict:
    funds = await list_funds(session, workspace_id, status="active")
    total_saved = sum(float(f.current_amount) for f in funds)
    total_target = sum(float(f.target_amount) for f in funds)
    monthly_needed = sum(f.suggested_monthly or 0 for f in funds)
    return {
        "count": len(funds),
        "total_saved": round(total_saved, 2),
        "total_target": round(total_target, 2),
        "monthly_needed": round(monthly_needed, 2),
    }
