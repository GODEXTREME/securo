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
from app.schemas.asset_income import AssetIncomeCreate, AssetIncomeRead, AssetIncomeUpdate
from app.services import asset_income_service

router = APIRouter(prefix="/api/asset-income", tags=["asset-income"])


@router.get("", response_model=list[AssetIncomeRead])
async def list_income(
    asset_id: Optional[uuid.UUID] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await asset_income_service.list_income(session, ctx.workspace.id, asset_id)


@router.get("/summary")
async def summary(
    months: int = Query(12, ge=1, le=60),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await asset_income_service.summary(session, ctx.workspace.id, ctx.user_id, months)


@router.post("", response_model=AssetIncomeRead, status_code=status.HTTP_201_CREATED)
async def create_income(
    data: AssetIncomeCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await asset_income_service.create_income(session, ctx.workspace.id, ctx.user_id, data)


@router.patch("/{income_id}", response_model=AssetIncomeRead)
async def update_income(
    income_id: uuid.UUID,
    data: AssetIncomeUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    inc = await asset_income_service.update_income(session, income_id, ctx.workspace.id, data)
    if not inc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Income entry not found")
    return inc


@router.delete("/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_income(
    income_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    ok = await asset_income_service.delete_income(session, income_id, ctx.workspace.id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Income entry not found")
