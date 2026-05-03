import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserManager, current_active_user, current_superuser, get_user_manager
from app.core.database import get_async_session
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserList,
    AdminUserRead,
    AdminUserUpdate,
    AppSettingRead,
    AppSettingUpdate,
)
from app.services import admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])

ALLOWED_SETTINGS = {
    "registration_enabled",
    "credit_card_accounting_mode",
    "use_provider_categories",
    "accounts_view_mode",
}


@router.get("/users", response_model=AdminUserList)
async def list_users(
    search: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    users, total = await admin_service.list_users(session, search, page, limit)
    return AdminUserList(
        items=[AdminUserRead.model_validate(u) for u in users],
        total=total,
    )


@router.post("/users", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: AdminUserCreate,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
    user_manager: UserManager = Depends(get_user_manager),
):
    try:
        user = await admin_service.create_user(session, user_manager, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return AdminUserRead.model_validate(user)


@router.get("/users/{user_id}", response_model=AdminUserRead)
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    user = await admin_service.get_user(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return AdminUserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(current_superuser),
):
    try:
        user = await admin_service.update_user(session, user_id, data, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return AdminUserRead.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(current_superuser),
):
    try:
        deleted = await admin_service.delete_user(session, user_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.get("/settings/{key}", response_model=AppSettingRead)
async def get_setting(
    key: str,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    setting = await admin_service.get_app_setting(session, key)
    if not setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
    return AppSettingRead.model_validate(setting)


@router.patch("/settings/{key}", response_model=AppSettingRead)
async def update_setting(
    key: str,
    data: AppSettingUpdate,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    if key not in ALLOWED_SETTINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Setting '{key}' is not configurable",
        )
    SETTING_VALIDATORS = {
        "registration_enabled": {"true", "false"},
        "credit_card_accounting_mode": {"cash", "accrual"},
        "use_provider_categories": {"true", "false"},
        "accounts_view_mode": {"grouped", "compact"},
    }
    if key in SETTING_VALIDATORS and data.value not in SETTING_VALIDATORS[key]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid value for '{key}'. Allowed: {SETTING_VALIDATORS[key]}",
        )
    setting = await admin_service.set_app_setting(session, key, data.value)
    return AppSettingRead.model_validate(setting)


@router.get("/registration-status")
async def registration_status(
    session: AsyncSession = Depends(get_async_session),
):
    enabled = await admin_service.is_registration_enabled(session)
    return {"enabled": enabled}


@router.get("/accounting-mode")
async def accounting_mode(
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_active_user),
):
    mode = await admin_service.get_credit_card_accounting_mode(session)
    return {"mode": mode}


@router.get("/accounts-view-mode")
async def accounts_view_mode(
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_active_user),
):
    mode = await admin_service.get_accounts_view_mode(session)
    return {"mode": mode}


async def check_registration_enabled(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    enabled = await admin_service.is_registration_enabled(session)
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently disabled",
        )
