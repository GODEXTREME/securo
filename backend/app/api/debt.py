from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import debt_service

router = APIRouter(prefix="/api/debt", tags=["debt"])


class DebtOverride(BaseModel):
    name: str
    balance: float
    apr: float
    min_payment: float


class PlanRequest(BaseModel):
    extra_payment: float = 0.0
    debts: Optional[list[DebtOverride]] = None


@router.get("/accounts")
async def debt_accounts(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await debt_service.get_debt_accounts(session, ctx.workspace.id)


@router.post("/plan")
async def debt_plan(
    body: PlanRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    overrides = None
    if body.debts:
        overrides = [
            {"name": d.name, "balance": d.balance, "apr": d.apr, "min_payment": d.min_payment}
            for d in body.debts
        ]
    return await debt_service.plan(session, ctx.workspace.id, body.extra_payment, overrides)
