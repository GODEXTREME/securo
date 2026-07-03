import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.schemas.notification import NotificationList, NotificationRead, UnreadCount
from app.services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    items, unread = await notification_service.list_notifications(
        session, ctx.workspace.id, ctx.user_id, unread_only, limit
    )
    return NotificationList(
        items=[NotificationRead.model_validate(n) for n in items], unread=unread
    )


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return UnreadCount(unread=await notification_service.unread_count(session, ctx.workspace.id, ctx.user_id))


@router.post("/refresh", response_model=UnreadCount)
async def refresh(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Recompute alerts for the current workspace, then return the unread count."""
    await notification_service.generate_for_workspace(session, ctx.workspace.id, ctx.user_id)
    return UnreadCount(unread=await notification_service.unread_count(session, ctx.workspace.id, ctx.user_id))


@router.post("/{notif_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notif_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    ok = await notification_service.mark_read(session, notif_id, ctx.workspace.id, ctx.user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")


@router.post("/read-all", response_model=UnreadCount)
async def mark_all_read(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    await notification_service.mark_all_read(session, ctx.workspace.id, ctx.user_id)
    return UnreadCount(unread=0)


@router.delete("/{notif_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notif_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    ok = await notification_service.delete_notification(session, notif_id, ctx.workspace.id, ctx.user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
