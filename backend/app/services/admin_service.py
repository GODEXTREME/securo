import uuid
from typing import Optional

from fastapi_users.exceptions import UserAlreadyExists
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserManager
from app.core.config import get_settings
from app.models.app_settings import AppSetting
from app.models.user import User
from app.schemas.admin import AdminUserCreate, AdminUserUpdate


async def list_users(
    session: AsyncSession,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[User], int]:
    query = select(User)
    count_query = select(func.count()).select_from(User)

    if search:
        query = query.where(User.email.ilike(f"%{search}%"))
        count_query = count_query.where(User.email.ilike(f"%{search}%"))

    total = (await session.execute(count_query)).scalar() or 0

    query = query.order_by(User.email).offset((page - 1) * limit).limit(limit)
    result = await session.execute(query)
    users = list(result.scalars().all())

    return users, total


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    user_manager: UserManager,
    data: AdminUserCreate,
) -> User:
    from fastapi_users.schemas import BaseUserCreate

    create_schema = BaseUserCreate(
        email=data.email,
        password=data.password,
        is_superuser=data.is_superuser,
        is_active=True,
        is_verified=True,
    )

    try:
        user = await user_manager.create(create_schema)
    except UserAlreadyExists:
        raise ValueError("A user with this email already exists")

    # Set preferences if provided
    if data.preferences:
        user.preferences = data.preferences
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user


async def update_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    current_user_id: uuid.UUID,
) -> Optional[User]:
    user = await get_user(session, user_id)
    if not user:
        return None

    # Self-protection: can't demote or deactivate self
    if user_id == current_user_id:
        if data.is_superuser is False:
            raise ValueError("Cannot remove your own admin privileges")
        if data.is_active is False:
            raise ValueError("Cannot deactivate your own account")

    if data.email is not None and data.email != user.email:
        existing = await session.execute(
            select(User).where(User.email == data.email)
        )
        if existing.scalar_one_or_none():
            raise ValueError("A user with this email already exists")
        user.email = data.email
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_superuser is not None:
        user.is_superuser = data.is_superuser
    if data.preferences is not None:
        user.preferences = data.preferences
    if data.password is not None:
        from fastapi_users.password import PasswordHelper

        password_helper = PasswordHelper()
        user.hashed_password = password_helper.hash(data.password)

    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> bool:
    if user_id == current_user_id:
        raise ValueError("Cannot delete your own account")

    user = await get_user(session, user_id)
    if not user:
        return False

    # Check last superuser protection
    if user.is_superuser:
        count_result = await session.execute(
            select(func.count()).select_from(User).where(
                User.is_superuser == True,  # noqa: E712
                User.is_active == True,  # noqa: E712
            )
        )
        superuser_count = count_result.scalar() or 0
        if superuser_count <= 1:
            raise ValueError("Cannot delete the last admin user")

    # Cascade delete user data in correct order
    from app.models.transaction_attachment import TransactionAttachment
    from app.models.transaction import Transaction
    from app.models.budget import Budget
    from app.models.recurring_transaction import RecurringTransaction
    from app.models.import_log import ImportLog
    from app.models.rule import Rule
    from app.models.asset_value import AssetValue
    from app.models.asset import Asset
    from app.models.payee import PayeeMapping, Payee
    from app.models.account import Account
    from app.models.category import Category
    from app.models.category_group import CategoryGroup
    from app.models.bank_connection import BankConnection

    # Delete attachments for user's transactions
    tx_ids_query = select(Transaction.id).where(Transaction.user_id == user_id)
    await session.execute(
        delete(TransactionAttachment).where(
            TransactionAttachment.transaction_id.in_(tx_ids_query)
        )
    )

    # Delete in dependency order
    await session.execute(delete(Transaction).where(Transaction.user_id == user_id))
    await session.execute(delete(Budget).where(Budget.user_id == user_id))
    await session.execute(delete(RecurringTransaction).where(RecurringTransaction.user_id == user_id))
    await session.execute(delete(ImportLog).where(ImportLog.user_id == user_id))
    await session.execute(delete(Rule).where(Rule.user_id == user_id))

    # Asset values depend on assets
    asset_ids_query = select(Asset.id).where(Asset.user_id == user_id)
    await session.execute(
        delete(AssetValue).where(AssetValue.asset_id.in_(asset_ids_query))
    )
    await session.execute(delete(Asset).where(Asset.user_id == user_id))

    await session.execute(delete(PayeeMapping).where(PayeeMapping.user_id == user_id))
    await session.execute(delete(Payee).where(Payee.user_id == user_id))
    await session.execute(delete(Account).where(Account.user_id == user_id))
    await session.execute(delete(Category).where(Category.user_id == user_id))
    await session.execute(delete(CategoryGroup).where(CategoryGroup.user_id == user_id))
    await session.execute(delete(BankConnection).where(BankConnection.user_id == user_id))

    # Delete the user
    await session.delete(user)
    await session.commit()
    return True


async def get_app_setting(session: AsyncSession, key: str) -> Optional[AppSetting]:
    result = await session.execute(
        select(AppSetting).where(AppSetting.key == key)
    )
    return result.scalar_one_or_none()


async def set_app_setting(session: AsyncSession, key: str, value: str) -> AppSetting:
    setting = await get_app_setting(session, key)
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=key, value=value)
    session.add(setting)
    await session.commit()
    await session.refresh(setting)
    return setting


async def is_registration_enabled(session: AsyncSession) -> bool:
    setting = await get_app_setting(session, "registration_enabled")
    if setting:
        return setting.value.lower() == "true"
    # Fall back to env var
    return get_settings().registration_enabled


async def get_credit_card_accounting_mode(session: AsyncSession) -> str:
    """Return the global CC accounting mode: 'cash' or 'accrual'.

    Global app setting — affects how dashboard/reports/budgets bucket credit
    card transactions. Defaults to 'cash' (current behavior) when unset."""
    setting = await get_app_setting(session, "credit_card_accounting_mode")
    if setting and setting.value in ("cash", "accrual"):
        return setting.value
    return "cash"


async def get_accounts_view_mode(session: AsyncSession) -> str:
    """Return the global Accounts page view mode: 'grouped' or 'compact'.

    Global app setting — affects how bank connections are displayed on the
    Accounts page. Defaults to 'grouped' (current behavior) when unset."""
    setting = await get_app_setting(session, "accounts_view_mode")
    if setting and setting.value in ("grouped", "compact"):
        return setting.value
    return "grouped"


async def use_provider_categories(session: AsyncSession) -> bool:
    """Whether sync should map provider-supplied categories (e.g. Pluggy's
    `category` field) onto the user's seeded categories via PLUGGY_CATEGORY_MAP.

    Global app setting — affects every connection's sync. Defaults to True
    (preserves current behavior). Admins can flip it off when the provider's
    classification is consistently wrong and they'd rather have everything
    arrive uncategorized so user-defined Rules are the only source of truth."""
    setting = await get_app_setting(session, "use_provider_categories")
    if setting:
        return setting.value.lower() == "true"
    return True
