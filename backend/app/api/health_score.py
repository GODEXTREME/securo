from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import health_service

# Note: path is /api/health-score to avoid clashing with the /api/health probe.
router = APIRouter(prefix="/api/health-score", tags=["health-score"])


@router.get("")
async def get_health_score(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await health_service.get_health_score(session, ctx.workspace.id, ctx.user_id)
