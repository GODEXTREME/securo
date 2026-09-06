"""A physical store, as the note identifies it: one CNPJ.

Instance-wide, not workspace-scoped. A store is a public fact — its CNPJ
and address are printed on every receipt it issues — and one row per
CNPJ is what lets two workspaces that shop at the same place share a
price history. `cnpj_root` (the first eight digits) is the chain: every
branch of a retailer shares it, and it is what scopes a store-internal
product code (see `product_aliases` kind `chain`).

Deliberately no link to `payees`: a payee belongs to a workspace and a
store belongs to the instance. The transaction match that would want one
works by name similarity instead, per workspace.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True, index=True)
    cnpj_root: Mapped[str] = mapped_column(String(8), index=True)
    ie: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    legal_name: Mapped[str] = mapped_column(String(255))
    trade_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    street: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    number: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    district: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    uf: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    zip: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
