import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class FixedIncomeOption(Base):
    """A fixed-income product the user is tracking to compare (CDB, LCI/LCA,
    Tesouro Direto, poupança, ...).

    The stored ``rate`` is interpreted by ``rate_kind``: ``cdi`` = percent of the
    CDI, ``prefixed`` = fixed % per year, ``ipca_plus`` = IPCA + % per year. The
    comparison service turns these into a comparable net annual yield after
    income tax (unless ``tax_exempt``) using a reference CDI/IPCA.
    """

    __tablename__ = "fixed_income_options"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    institution: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    product_type: Mapped[str] = mapped_column(String(40), default="CDB")
    rate_kind: Mapped[str] = mapped_column(String(20), default="cdi")  # cdi | prefixed | ipca_plus
    rate: Mapped[Decimal] = mapped_column(Numeric(precision=8, scale=2), default=Decimal("0.00"))
    liquidity: Mapped[str] = mapped_column(String(20), default="daily")  # daily | maturity
    maturity_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    min_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    tax_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship()
