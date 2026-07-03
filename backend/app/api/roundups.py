from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import roundup_service

router = APIRouter(prefix="/api/roundups", tags=["roundups"])


@router.get("")
async def get_roundups(
    months: int = Query(1, ge=1, le=12),
    multiplier: int = Query(1, ge=1, le=10),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await roundup_service.get_roundups(
        session, ctx.workspace.id, ctx.user_id, months, multiplier
    )
