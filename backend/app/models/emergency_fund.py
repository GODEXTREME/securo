import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.user import User


class EmergencyFund(Base):
    """A workspace's emergency-fund plan (one row per workspace).

    Stores the target size in months of expenses and how much is set aside —
    either a manually entered amount or the live balance of a linked account.
    The target value and progress are computed from the workspace's average
    monthly spending.
    """

    __tablename__ = "emergency_funds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True, index=True
    )
    target_months: Mapped[int] = mapped_column(Integer, default=6)
    current_amount: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    # When set, the account's balance is used instead of current_amount.
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    monthly_contribution: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship()
    account: Mapped[Optional["Account"]] = relationship()
