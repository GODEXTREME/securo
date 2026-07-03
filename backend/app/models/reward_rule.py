import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.category import Category
    from app.models.user import User


class RewardRule(Base):
    """A cashback / rewards rule for a card (account).

    "This card gives X% back on category Y." A rule with no ``category_id`` is
    the card's default (fallback) rate. Earned rewards are computed from the
    workspace's transactions by matching each spend to the most specific rule
    (a category-specific rule beats the card's default).
    """

    __tablename__ = "reward_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE")
    )
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), nullable=True
    )
    # Percentage back, e.g. 2.00 for 2%.
    rate: Mapped[Decimal] = mapped_column(Numeric(precision=6, scale=2), default=Decimal("0.00"))
    # Optional friendly label ("points program", "cashback", ...).
    name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship()
    account: Mapped["Account"] = relationship()
    category: Mapped[Optional["Category"]] = relationship()
