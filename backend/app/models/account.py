import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.bank_connection import BankConnection
    from app.models.transaction import Transaction


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("bank_connections.id"), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Last 4 chars of the bank's identifier (IBAN, account or card number), when
    # the provider exposes one. Provider-owned like `name`: refreshed on sync,
    # not user-editable. Never holds the full identifier.
    masked_number: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    type: Mapped[str] = mapped_column(String(50))  # checking, savings, credit_card
    balance: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    balance_primary: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    credit_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    statement_close_day: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    payment_due_day: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    # The provider's actual next close/due DATES (Pluggy balanceCloseDate /
    # balanceDueDate). Unlike the nominal *_day above, these reflect the bank's
    # real cycle — which shifts for weekends/holidays — so the open cycle's
    # boundary buckets exactly right before the bill links (issue: nominal day
    # misbucketed a boundary tx when the bank closed a day early/late).
    next_close_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    next_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    minimum_payment: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    # Annual percentage rate (e.g. 24.900 for 24.9%). Optional; feeds the debt
    # payoff planner. Numeric(6,3) covers rates up to 999.999%.
    apr: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=6, scale=3), nullable=True)
    card_brand: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    connection: Mapped[Optional["BankConnection"]] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account", cascade="all, delete-orphan")
