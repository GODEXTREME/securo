import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.schemas.fixed_income import (
    FixedIncomeOptionCreate,
    FixedIncomeOptionRead,
    FixedIncomeOptionUpdate,
)
from app.services import fixed_income_service

router = APIRouter(prefix="/api/fixed-income", tags=["fixed-income"])


@router.get("", response_model=list[FixedIncomeOptionRead])
async def list_options(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await fixed_income_service.list_options(session, ctx.workspace.id)


@router.get("/compare")
async def compare(
    amount: float = Query(1000.0, ge=0),
    horizon_days: int = Query(365, ge=1, le=36500),
    cdi: float = Query(10.5, ge=0, le=100),
    ipca: float = Query(4.0, ge=0, le=100),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await fixed_income_service.compare(session, ctx.workspace.id, amount, horizon_days, cdi, ipca)


@router.post("", response_model=FixedIncomeOptionRead, status_code=status.HTTP_201_CREATED)
async def create_option(
    data: FixedIncomeOptionCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await fixed_income_service.create_option(session, ctx.workspace.id, ctx.user_id, data)


@router.patch("/{option_id}", response_model=FixedIncomeOptionRead)
async def update_option(
    option_id: uuid.UUID,
    data: FixedIncomeOptionUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    opt = await fixed_income_service.update_option(session, option_id, ctx.workspace.id, data)
    if not opt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fixed-income option not found")
    return opt


@router.delete("/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_option(
    option_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    ok = await fixed_income_service.delete_option(session, option_id, ctx.workspace.id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fixed-income option not found")
