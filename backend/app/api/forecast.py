from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import forecast_service

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


@router.get("")
async def get_forecast(
    days: int = Query(90, ge=7, le=365),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await forecast_service.get_forecast(session, ctx.workspace.id, ctx.user_id, days)
