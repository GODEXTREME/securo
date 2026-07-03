"""Fixed-income (renda fixa) comparator.

Users register the products they're eyeing across different banks (CDB, LCI/LCA,
Tesouro, poupança) with their headline rate. The comparison turns each headline
rate into a comparable **net** annual yield after income tax (using Brazil's
regressive IR table for the chosen horizon, skipped for tax-exempt products like
LCI/LCA/poupança) against a reference CDI/IPCA, and projects the net earnings on
a given amount — highlighting the best option and the best daily-liquidity one.
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fixed_income_option import FixedIncomeOption
from app.schemas.fixed_income import (
    FixedIncomeOptionCreate,
    FixedIncomeOptionRead,
    FixedIncomeOptionUpdate,
)


def _ir_rate(days: int) -> float:
    """Brazilian regressive income-tax rate on fixed-income earnings, by holding days."""
    if days <= 180:
        return 22.5
    if days <= 360:
        return 20.0
    if days <= 720:
        return 17.5
    return 15.0


def _gross_annual(opt: FixedIncomeOption, cdi: float, ipca: float) -> float:
    rate = float(opt.rate)
    if opt.rate_kind == "cdi":
        return rate / 100.0 * cdi
    if opt.rate_kind == "ipca_plus":
        return ipca + rate
    return rate  # prefixed


async def list_options(session: AsyncSession, workspace_id: uuid.UUID) -> list[FixedIncomeOptionRead]:
    stmt = (
        select(FixedIncomeOption)
        .where(FixedIncomeOption.workspace_id == workspace_id)
        .order_by(FixedIncomeOption.created_at)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return [FixedIncomeOptionRead.model_validate(o) for o in rows]


async def get_option(
    session: AsyncSession, option_id: uuid.UUID, workspace_id: uuid.UUID
) -> Optional[FixedIncomeOption]:
    opt = await session.get(FixedIncomeOption, option_id)
    if not opt or opt.workspace_id != workspace_id:
        return None
    return opt


async def create_option(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, data: FixedIncomeOptionCreate
) -> FixedIncomeOptionRead:
    opt = FixedIncomeOption(
        user_id=user_id,
        workspace_id=workspace_id,
        name=data.name,
        institution=data.institution,
        product_type=data.product_type,
        rate_kind=data.rate_kind,
        rate=data.rate,
        liquidity=data.liquidity,
        maturity_date=data.maturity_date,
        min_amount=data.min_amount,
        tax_exempt=data.tax_exempt,
    )
    session.add(opt)
    await session.commit()
    await session.refresh(opt)
    return FixedIncomeOptionRead.model_validate(opt)


async def update_option(
    session: AsyncSession, option_id: uuid.UUID, workspace_id: uuid.UUID, data: FixedIncomeOptionUpdate
) -> Optional[FixedIncomeOptionRead]:
    opt = await get_option(session, option_id, workspace_id)
    if not opt:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(opt, key, value)
    await session.commit()
    await session.refresh(opt)
    return FixedIncomeOptionRead.model_validate(opt)


async def delete_option(session: AsyncSession, option_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
    opt = await get_option(session, option_id, workspace_id)
    if not opt:
        return False
    await session.delete(opt)
    await session.commit()
    return True


async def compare(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    amount: float = 1000.0,
    horizon_days: int = 365,
    cdi: float = 10.5,
    ipca: float = 4.0,
) -> dict:
    amount = max(0.0, float(amount))
    horizon_days = max(1, int(horizon_days))
    ir = _ir_rate(horizon_days)
    years = horizon_days / 365.0

    options = list((await session.execute(
        select(FixedIncomeOption).where(FixedIncomeOption.workspace_id == workspace_id)
    )).scalars().all())

    items: list[dict] = []
    for opt in options:
        gross_annual = _gross_annual(opt, cdi, ipca)
        opt_ir = 0.0 if opt.tax_exempt else ir
        gross_earn = amount * ((1.0 + gross_annual / 100.0) ** years - 1.0)
        net_earn = gross_earn * (1.0 - opt_ir / 100.0)
        net_annual = gross_annual * (1.0 - opt_ir / 100.0)
        items.append({
            "id": str(opt.id),
            "name": opt.name,
            "institution": opt.institution,
            "product_type": opt.product_type,
            "rate_kind": opt.rate_kind,
            "rate": float(opt.rate),
            "liquidity": opt.liquidity,
            "tax_exempt": opt.tax_exempt,
            "maturity_date": opt.maturity_date.isoformat() if opt.maturity_date else None,
            "min_amount": float(opt.min_amount) if opt.min_amount is not None else None,
            "gross_annual": round(gross_annual, 2),
            "ir_rate": round(opt_ir, 1),
            "net_annual": round(net_annual, 2),
            "gross_earnings": round(gross_earn, 2),
            "net_earnings": round(net_earn, 2),
            "final_amount": round(amount + net_earn, 2),
        })

    items.sort(key=lambda x: x["net_annual"], reverse=True)
    best_id = items[0]["id"] if items else None
    best_daily = next((it for it in items if it["liquidity"] == "daily"), None)

    return {
        "amount": round(amount, 2),
        "horizon_days": horizon_days,
        "cdi": cdi,
        "ipca": ipca,
        "ir_rate": round(ir, 1),
        "best_id": best_id,
        "best_daily_id": best_daily["id"] if best_daily else None,
        "options": items,
    }
