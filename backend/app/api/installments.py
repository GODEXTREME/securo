import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.services import installment_service, transaction_service

router = APIRouter(prefix="/api/installments", tags=["installments"])


@router.get("")
async def list_plans(
    only_uncategorized: bool = Query(False),
    account_id: Optional[uuid.UUID] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await installment_service.group_plans(
        session, ctx.workspace.id, only_uncategorized, account_id
    )


class CategorizePlanRequest(BaseModel):
    transaction_ids: list[uuid.UUID]
    category_id: Optional[uuid.UUID] = None


@router.patch("/categorize")
async def categorize_plan(
    data: CategorizePlanRequest,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Apply one category to every parcel of an installment plan."""
    count = await transaction_service.bulk_update_category(
        session, ctx.workspace.id, data.transaction_ids, data.category_id
    )
    return {"updated": count}
