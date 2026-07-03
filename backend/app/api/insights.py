from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import insight_service

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("")
async def get_insights(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await insight_service.get_insights(session, ctx.workspace.id, ctx.user_id)
