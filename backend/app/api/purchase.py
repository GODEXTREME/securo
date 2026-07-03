from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import purchase_service

router = APIRouter(prefix="/api/purchase", tags=["purchase"])


class CashVsInstallmentsRequest(BaseModel):
    cash_price: float = Field(ge=0)
    installment_total: float = Field(ge=0)
    n_installments: int = Field(ge=1, le=360)
    investment_rate: float = Field(0.0, ge=0, le=100)
    rate_period: str = Field("annual", pattern="^(annual|monthly)$")
    first_installment_today: bool = True
    currency: Optional[str] = None


@router.post("/cash-vs-installments")
async def cash_vs_installments(
    body: CashVsInstallmentsRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    currency = body.currency or ctx.user.primary_currency
    return purchase_service.compare(
        cash_price=body.cash_price,
        installment_total=body.installment_total,
        n_installments=body.n_installments,
        investment_rate=body.investment_rate,
        rate_period=body.rate_period,
        first_installment_today=body.first_installment_today,
        currency=currency,
    )
