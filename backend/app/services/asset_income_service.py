"""Asset income (dividends / JCP / rent / interest) tracking.

CRUD for payouts a holding generates, plus a summary that totals income per
asset, the monthly series and the yield on the amount invested.
"""
import uuid
from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.asset_income import AssetIncome
from app.schemas.asset_income import AssetIncomeCreate, AssetIncomeRead, AssetIncomeUpdate


def _shift_month(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


async def _to_read(session: AsyncSession, inc: AssetIncome) -> AssetIncomeRead:
    read = AssetIncomeRead.model_validate(inc)
    asset = await session.get(Asset, inc.asset_id)
    if asset:
        read.asset_name = asset.name
    return read


async def list_income(
    session: AsyncSession, workspace_id: uuid.UUID, asset_id: Optional[uuid.UUID] = None
) -> list[AssetIncomeRead]:
    stmt = select(AssetIncome).where(AssetIncome.workspace_id == workspace_id)
    if asset_id:
        stmt = stmt.where(AssetIncome.asset_id == asset_id)
    stmt = stmt.order_by(AssetIncome.date.desc())
    rows = list((await session.execute(stmt)).scalars().all())
    return [await _to_read(session, r) for r in rows]


async def get_income(session: AsyncSession, income_id: uuid.UUID, workspace_id: uuid.UUID) -> Optional[AssetIncome]:
    inc = await session.get(AssetIncome, income_id)
    if not inc or inc.workspace_id != workspace_id:
        return None
    return inc


async def create_income(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, data: AssetIncomeCreate
) -> AssetIncomeRead:
    inc = AssetIncome(
        user_id=user_id,
        workspace_id=workspace_id,
        asset_id=data.asset_id,
        date=data.date,
        amount=data.amount,
        currency=data.currency,
        kind=data.kind,
        note=data.note,
    )
    session.add(inc)
    await session.commit()
    await session.refresh(inc)
    return await _to_read(session, inc)


async def update_income(
    session: AsyncSession, income_id: uuid.UUID, workspace_id: uuid.UUID, data: AssetIncomeUpdate
) -> Optional[AssetIncomeRead]:
    inc = await get_income(session, income_id, workspace_id)
    if not inc:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(inc, key, value)
    await session.commit()
    await session.refresh(inc)
    return await _to_read(session, inc)


async def delete_income(session: AsyncSession, income_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
    inc = await get_income(session, income_id, workspace_id)
    if not inc:
        return False
    await session.delete(inc)
    await session.commit()
    return True


async def summary(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, months: int = 12
) -> dict:
    from app.services.advanced_report_service import _currency

    currency = await _currency(session, user_id)
    today = date.today()
    start = _shift_month(date(today.year, today.month, 1), max(0, months - 1))

    rows = list((await session.execute(
        select(AssetIncome).where(
            AssetIncome.workspace_id == workspace_id,
            AssetIncome.date >= start,
        )
    )).scalars().all())

    total = 0.0
    per_asset: dict[uuid.UUID, float] = defaultdict(float)
    per_month: dict[str, float] = defaultdict(float)
    for inc in rows:
        amt = float(inc.amount)
        total += amt
        per_asset[inc.asset_id] += amt
        per_month[inc.date.strftime("%Y-%m")] += amt

    by_asset = []
    for asset_id, asset_total in per_asset.items():
        asset = await session.get(Asset, asset_id)
        invested = 0.0
        if asset is not None:
            if asset.purchase_price_primary is not None:
                invested = float(asset.purchase_price_primary)
            elif asset.purchase_price is not None:
                invested = float(asset.purchase_price)
        by_asset.append({
            "asset_id": str(asset_id),
            "name": asset.name if asset else "?",
            "total": round(asset_total, 2),
            "invested": round(invested, 2),
            "yield_pct": round(asset_total / invested * 100, 2) if invested > 0 else None,
        })
    by_asset.sort(key=lambda a: a["total"], reverse=True)

    month_keys = [_shift_month(date(today.year, today.month, 1), k).strftime("%Y-%m")
                  for k in range(months - 1, -1, -1)]
    series = [{"month": mk, "total": round(per_month.get(mk, 0.0), 2)} for mk in month_keys]

    return {
        "currency": currency,
        "months": months,
        "total": round(total, 2),
        "monthly_average": round(total / months, 2) if months else 0.0,
        "by_asset": by_asset,
        "series": series,
    }
