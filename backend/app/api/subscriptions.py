from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.services import subscription_service

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.get("")
async def list_subscriptions(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await subscription_service.summarize(session, ctx.workspace.id)
