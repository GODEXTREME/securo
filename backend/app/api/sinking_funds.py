import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.schemas.sinking_fund import (
    ContributionRequest,
    SinkingFundCreate,
    SinkingFundRead,
    SinkingFundUpdate,
)
from app.services import sinking_fund_service

router = APIRouter(prefix="/api/sinking-funds", tags=["sinking-funds"])


@router.get("", response_model=list[SinkingFundRead])
async def list_funds(
    status: Optional[str] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await sinking_fund_service.list_funds(session, ctx.workspace.id, status)


@router.get("/summary")
async def summary(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await sinking_fund_service.summary(session, ctx.workspace.id)


@router.post("", response_model=SinkingFundRead, status_code=status.HTTP_201_CREATED)
async def create_fund(
    data: SinkingFundCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await sinking_fund_service.create_fund(session, ctx.workspace.id, ctx.user_id, data)


@router.patch("/{fund_id}", response_model=SinkingFundRead)
async def update_fund(
    fund_id: uuid.UUID,
    data: SinkingFundUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    fund = await sinking_fund_service.update_fund(session, fund_id, ctx.workspace.id, data)
    if not fund:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sinking fund not found")
    return fund


@router.post("/{fund_id}/contribute", response_model=SinkingFundRead)
async def contribute(
    fund_id: uuid.UUID,
    data: ContributionRequest,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    fund = await sinking_fund_service.contribute(session, fund_id, ctx.workspace.id, data.amount)
    if not fund:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sinking fund not found")
    return fund


@router.delete("/{fund_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fund(
    fund_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    ok = await sinking_fund_service.delete_fund(session, fund_id, ctx.workspace.id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sinking fund not found")
