from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import calendar_service

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("")
async def get_calendar(
    year: int = Query(..., ge=1970, le=2200),
    month: int = Query(..., ge=1, le=12),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await calendar_service.get_calendar(session, ctx.workspace.id, ctx.user_id, year, month)
