from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.schemas.emergency_fund import EmergencyFundRead, EmergencyFundUpdate
from app.services import emergency_fund_service

router = APIRouter(prefix="/api/emergency-fund", tags=["emergency-fund"])


@router.get("", response_model=EmergencyFundRead)
async def get_fund(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await emergency_fund_service.get(session, ctx.workspace.id, ctx.user_id, ctx.user.primary_currency)


@router.put("", response_model=EmergencyFundRead)
async def update_fund(
    data: EmergencyFundUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await emergency_fund_service.update(session, ctx.workspace.id, ctx.user_id, ctx.user.primary_currency, data)
