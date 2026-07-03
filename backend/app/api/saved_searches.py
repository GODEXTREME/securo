import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.models.saved_search import SavedSearch

router = APIRouter(prefix="/api/saved-searches", tags=["saved-searches"])


class SavedSearchCreate(BaseModel):
    name: str
    filters_json: Optional[Any] = None


class SavedSearchRead(BaseModel):
    id: uuid.UUID
    name: str
    filters_json: Optional[Any] = None
    position: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=list[SavedSearchRead])
async def list_searches(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(SavedSearch)
        .where(SavedSearch.workspace_id == ctx.workspace.id, SavedSearch.user_id == ctx.user_id)
        .order_by(SavedSearch.position, SavedSearch.created_at)
    )
    return list(result.scalars().all())


@router.post("", response_model=SavedSearchRead, status_code=status.HTTP_201_CREATED)
async def create_search(
    data: SavedSearchCreate,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    search = SavedSearch(
        user_id=ctx.user_id, workspace_id=ctx.workspace.id,
        name=data.name, filters_json=data.filters_json,
    )
    session.add(search)
    await session.commit()
    await session.refresh(search)
    return search


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search(
    search_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    search = await session.get(SavedSearch, search_id)
    if not search or search.workspace_id != ctx.workspace.id or search.user_id != ctx.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved search not found")
    await session.delete(search)
    await session.commit()
