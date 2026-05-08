import uuid
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.group import Group, GroupMember
from app.models.user import User
from app.schemas.group import (
    GroupCreate,
    GroupMemberCreate,
    GroupMemberUpdate,
    GroupUpdate,
)


def _tag_owner(group: Group, user_id: uuid.UUID) -> Group:
    """Set a transient `is_owner` flag for the response layer.

    Pydantic's from_attributes picks this up — the schema treats
    `is_owner` as derived per-request, not stored on the model.
    """
    group.is_owner = group.user_id == user_id  # type: ignore[attr-defined]
    if getattr(group, "members", None):
        for m in group.members:
            _tag_member_self(m, user_id, group.user_id)
    return group


def _tag_member_self(
    member: GroupMember, user_id: uuid.UUID, group_owner_id: uuid.UUID
) -> GroupMember:
    """Override `is_self` per-request so the "(you)" tag tracks the
    requesting user rather than the stored flag (which only marks the
    owner's own member). Falls back to the stored flag for an owner
    whose self-member isn't linked to a Securo account.
    """
    is_linked_to_caller = (
        member.linked_user_id is not None and member.linked_user_id == user_id
    )
    is_owner_self_unlinked = (
        group_owner_id == user_id
        and member.linked_user_id is None
        and bool(member.is_self)
    )
    member.is_self = is_linked_to_caller or is_owner_self_unlinked
    return member


async def _resolve_member_email(
    session: AsyncSession, email: Optional[str]
) -> Optional[uuid.UUID]:
    """If `email` matches an existing Securo user, return their id.
    Otherwise return None — the member is created as a shadow row."""
    if not email:
        return None
    result = await session.execute(
        select(User.id).where(func.lower(User.email) == email.strip().lower())
    )
    return result.scalar_one_or_none()


def _visible_predicate(user_id: uuid.UUID):
    """Group is visible if the user is the owner OR linked as a member.
    Implemented as a subquery so the filter survives joins/options."""
    member_groups = (
        select(GroupMember.group_id)
        .where(GroupMember.linked_user_id == user_id)
        .distinct()
    )
    return or_(Group.user_id == user_id, Group.id.in_(member_groups))


async def list_groups(
    session: AsyncSession, user_id: uuid.UUID, include_archived: bool = False
) -> list[Group]:
    query = (
        select(Group)
        .where(_visible_predicate(user_id))
        .options(selectinload(Group.members))
        .order_by(Group.created_at.desc())
    )
    if not include_archived:
        query = query.where(Group.is_archived.is_(False))
    result = await session.execute(query)
    return [_tag_owner(g, user_id) for g in result.scalars().all()]


async def get_group(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> Optional[Group]:
    """Returns the group if the user is the owner. Used by edit paths
    that need to enforce ownership."""
    result = await session.execute(
        select(Group)
        .where(Group.id == group_id, Group.user_id == user_id)
        .options(selectinload(Group.members))
    )
    group = result.scalar_one_or_none()
    if group is not None:
        _tag_owner(group, user_id)
    return group


async def get_group_visible(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> Optional[Group]:
    """Returns the group if the user is the owner OR a linked member.
    Use for read-only endpoints that should also serve members."""
    result = await session.execute(
        select(Group)
        .where(Group.id == group_id, _visible_predicate(user_id))
        .options(selectinload(Group.members))
    )
    group = result.scalar_one_or_none()
    if group is not None:
        _tag_owner(group, user_id)
    return group


async def create_group(
    session: AsyncSession, user_id: uuid.UUID, data: GroupCreate
) -> Group:
    existing = await session.execute(
        select(Group).where(
            Group.user_id == user_id,
            func.lower(Group.name) == data.name.strip().lower(),
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("A group with this name already exists")

    group = Group(user_id=user_id, **data.model_dump())
    session.add(group)
    await session.flush()
    # Eager-load members so the response shape stays stable.
    await session.refresh(group, attribute_names=["members"])
    await session.commit()
    return _tag_owner(group, user_id)


async def update_group(
    session: AsyncSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    data: GroupUpdate,
) -> Optional[Group]:
    group = await get_group(session, group_id, user_id)
    if not group:
        return None

    update_data = data.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"]:
        clash = await session.execute(
            select(Group).where(
                Group.user_id == user_id,
                func.lower(Group.name) == update_data["name"].strip().lower(),
                Group.id != group_id,
            )
        )
        if clash.scalar_one_or_none():
            raise ValueError("A group with this name already exists")

    for key, value in update_data.items():
        setattr(group, key, value)

    await session.commit()
    await session.refresh(group, attribute_names=["members"])
    return _tag_owner(group, user_id)


async def delete_group(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    group = await get_group(session, group_id, user_id)
    if not group:
        return False
    try:
        await session.delete(group)
        await session.commit()
    except IntegrityError as e:
        # A member with active splits or settlements (RESTRICT FK)
        # blocks the cascade. Translate into a 409-friendly error.
        await session.rollback()
        raise ValueError(
            "Group has members referenced by transaction splits or settlements. "
            "Remove those first."
        ) from e
    return True


async def list_members(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> Optional[list[GroupMember]]:
    # Skip the eager-loaded `Group.members` collection here — within a
    # long-lived session (notably tests) the identity map can hold a
    # stale snapshot after upstream mutations like `_clear_self_flag`.
    # A direct query always reflects the current row state.
    # Visible to owners AND linked members (read-only context).
    group = await get_group_visible(session, group_id, user_id)
    if not group:
        return None
    result = await session.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.created_at)
    )
    return [_tag_member_self(m, user_id, group.user_id) for m in result.scalars().all()]


async def create_member(
    session: AsyncSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    data: GroupMemberCreate,
) -> Optional[GroupMember]:
    group = await get_group(session, group_id, user_id)
    if not group:
        return None

    clash = await session.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            func.lower(GroupMember.name) == data.name.strip().lower(),
        )
    )
    if clash.scalar_one_or_none():
        raise ValueError("A member with this name already exists in this group")

    if data.is_self:
        # Only one self-member per group; demote any existing one.
        await _clear_self_flag(session, group_id)

    payload = data.model_dump()
    if payload.get("email") is not None:
        payload["email"] = str(payload["email"])
    # Auto-link to a real Securo user if the email matches one. The
    # caller can override by passing linked_user_id explicitly.
    if payload.get("linked_user_id") is None:
        payload["linked_user_id"] = await _resolve_member_email(session, payload.get("email"))
    member = GroupMember(group_id=group_id, **payload)
    session.add(member)
    await session.commit()
    await session.refresh(member)
    return member


async def update_member(
    session: AsyncSession,
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    user_id: uuid.UUID,
    data: GroupMemberUpdate,
) -> Optional[GroupMember]:
    group = await get_group(session, group_id, user_id)
    if not group:
        return None

    result = await session.execute(
        select(GroupMember).where(
            GroupMember.id == member_id, GroupMember.group_id == group_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        return None

    update_data = data.model_dump(exclude_unset=True)
    if update_data.get("email") is not None:
        update_data["email"] = str(update_data["email"])
    if "name" in update_data and update_data["name"]:
        clash = await session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                func.lower(GroupMember.name) == update_data["name"].strip().lower(),
                GroupMember.id != member_id,
            )
        )
        if clash.scalar_one_or_none():
            raise ValueError("A member with this name already exists in this group")

    if update_data.get("is_self") is True:
        await _clear_self_flag(session, group_id, except_id=member_id)

    # Re-resolve the email link only when the caller is changing email
    # AND not explicitly overriding linked_user_id in the same request.
    if "email" in update_data and "linked_user_id" not in update_data:
        update_data["linked_user_id"] = await _resolve_member_email(
            session, update_data.get("email")
        )

    for key, value in update_data.items():
        setattr(member, key, value)

    await session.commit()
    await session.refresh(member)
    return member


async def delete_member(
    session: AsyncSession,
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    group = await get_group(session, group_id, user_id)
    if not group:
        return False

    result = await session.execute(
        select(GroupMember).where(
            GroupMember.id == member_id, GroupMember.group_id == group_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        return False

    try:
        await session.delete(member)
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise ValueError(
            "Member is referenced by transaction splits or settlements. "
            "Remove those first."
        ) from e
    return True


async def list_transactions(
    session: AsyncSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int = 20,
) -> Optional[list]:
    """Return the most recent transactions whose splits reference any
    member of this group. Visible to owner + linked members."""
    from sqlalchemy.orm import selectinload as _sel

    from app.models.transaction import Transaction
    from app.models.transaction_split import TransactionSplit

    if not await get_group_visible(session, group_id, user_id):
        return None

    member_ids_subq = select(GroupMember.id).where(GroupMember.group_id == group_id)
    tx_ids_subq = (
        select(TransactionSplit.transaction_id)
        .where(TransactionSplit.group_member_id.in_(member_ids_subq))
        .distinct()
    )
    result = await session.execute(
        select(Transaction)
        .where(Transaction.id.in_(tx_ids_subq))
        .options(
            _sel(Transaction.category),
            _sel(Transaction.account),
            _sel(Transaction.payee_entity),
            _sel(Transaction.splits),
        )
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .limit(limit)
    )
    txs = list(result.scalars().all())
    # Hydrate fields the TransactionRead schema expects.
    for tx in txs:
        tx.attachment_count = 0
        tx.payee_name = tx.payee_entity.name if tx.payee_entity else None
    return txs


async def _clear_self_flag(
    session: AsyncSession, group_id: uuid.UUID, except_id: Optional[uuid.UUID] = None
) -> None:
    query = select(GroupMember).where(
        GroupMember.group_id == group_id, GroupMember.is_self.is_(True)
    )
    if except_id is not None:
        query = query.where(GroupMember.id != except_id)
    result = await session.execute(query)
    for m in result.scalars().all():
        m.is_self = False
