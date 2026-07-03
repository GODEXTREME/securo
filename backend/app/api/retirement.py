from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import retirement_service

router = APIRouter(prefix="/api/retirement", tags=["retirement"])


class RetirementRequest(BaseModel):
    monthly_contribution: float = Field(0.0, ge=0)
    annual_return: float = Field(6.0, ge=0, le=100)
    annual_expenses: float = Field(0.0, ge=0)
    withdrawal_rate: float = Field(4.0, gt=0, le=100)
    current_age: Optional[int] = Field(None, ge=0, le=120)
    current_net_worth: Optional[float] = None


@router.get("/defaults")
async def retirement_defaults(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Prefill values: current net worth and a suggested monthly contribution."""
    currency = ctx.user.primary_currency
    nw = await retirement_service.current_net_worth(session, ctx.workspace.id, currency)
    suggested = await retirement_service.suggest_monthly_contribution(session, ctx.workspace.id)
    return {
        "currency": currency,
        "current_net_worth": nw,
        "suggested_monthly_contribution": suggested,
    }


@router.post("/project")
async def retirement_project(
    body: RetirementRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    currency = ctx.user.primary_currency
    nw = body.current_net_worth
    if nw is None:
        nw = await retirement_service.current_net_worth(session, ctx.workspace.id, currency)
    return retirement_service.project(
        current_net_worth=nw,
        monthly_contribution=body.monthly_contribution,
        annual_return=body.annual_return,
        annual_expenses=body.annual_expenses,
        withdrawal_rate=body.withdrawal_rate,
        current_age=body.current_age,
        currency=currency,
    )
