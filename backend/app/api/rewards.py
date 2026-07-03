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
from app.schemas.reward import RewardRuleCreate, RewardRuleRead, RewardRuleUpdate
from app.services import reward_service

router = APIRouter(prefix="/api/rewards", tags=["rewards"])


@router.get("", response_model=list[RewardRuleRead])
async def list_rules(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await reward_service.list_rules(session, ctx.workspace.id)


@router.get("/summary")
async def summary(
    year: Optional[int] = Query(None, ge=1970, le=2200),
    month: Optional[int] = Query(None, ge=1, le=12),
    months: int = Query(1, ge=1, le=24),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await reward_service.summary(session, ctx.workspace.id, ctx.user_id, year, month, months)


@router.post("", response_model=RewardRuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    data: RewardRuleCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await reward_service.create_rule(session, ctx.workspace.id, ctx.user_id, data)


@router.patch("/{rule_id}", response_model=RewardRuleRead)
async def update_rule(
    rule_id: uuid.UUID,
    data: RewardRuleUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    rule = await reward_service.update_rule(session, rule_id, ctx.workspace.id, data)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reward rule not found")
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    ok = await reward_service.delete_rule(session, rule_id, ctx.workspace.id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reward rule not found")
