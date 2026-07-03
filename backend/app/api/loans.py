from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import loan_service

router = APIRouter(prefix="/api/loans", tags=["loans"])


class LoanSimRequest(BaseModel):
    principal: float = Field(gt=0)
    rate: float = Field(ge=0)
    months: int = Field(ge=1, le=600)
    rate_period: str = Field("annual", pattern="^(annual|monthly)$")
    extra_payment: float = Field(0.0, ge=0)
    method: str = Field("both", pattern="^(both|price|sac)$")
    currency: Optional[str] = None


@router.post("/simulate")
async def simulate_loan(
    body: LoanSimRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    currency = body.currency or ctx.user.primary_currency
    return loan_service.simulate(
        principal=body.principal,
        rate=body.rate,
        months=body.months,
        rate_period=body.rate_period,
        extra_payment=body.extra_payment,
        method=body.method,
        currency=currency,
    )
