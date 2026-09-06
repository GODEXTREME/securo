"""Consumer receipts (NFC-e) and the queue that fetches them.

Two scopes in three tables, and the split is the point:

  - `receipts` and `receipt_items` are **instance-wide**. A note is a
    public fact to anyone holding its access key; caching it once per
    key is what keeps the state portal from being asked twice for the
    same document, and what lets two workspaces share one price history.
  - `receipt_links` is **per workspace**. Having scanned a note is the
    personal fact: it is what appears in your list, what "not my
    purchase" is a flag on, what a transaction gets matched to, and what
    is deleted with the workspace. The note itself stays.

The fetch queue lives on `receipts` rather than in a table of its own.
There is exactly one job per key and fetching is idempotent, so a second
table would only repeat the primary key. `status` is the state machine;
`attempts`, `next_attempt_at` and `locked_at` are the queue.
"""
import uuid
from datetime import date as _date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.store import Store
    from app.models.transaction import Transaction
    from app.models.user import User
    from app.models.workspace import Workspace

#: The state machine. Only three transitions are taken by a human (manual
#: retry, pasting the page, editing); every other one is the worker's.
#:
#:   invalid        — a real key we will never fetch: wrong environment,
#:                    not an NFC-e, a state without an adapter, a QR that
#:                    points at a host we do not allow. Terminal.
#:   pending        — queued; first attempt is immediate.
#:   fetching       — claimed by a worker (`locked_at`).
#:   waiting_sefaz  — the portal did not have it (yet), was down, throttled
#:                    us, or asked for a human. `status_reason` says which.
#:   authorized     — parsed; items, store, totals persisted.
#:   parse_error    — the page was authorised but unreadable. Raw HTML kept
#:                    for when the parser improves.
#:   cancelled      — the state says it was cancelled. Terminal.
#:   gave_up        — the retry schedule ran out. A manual retry re-enters.
RECEIPT_STATUSES = (
    "invalid", "pending", "fetching", "waiting_sefaz",
    "authorized", "parse_error", "cancelled", "gave_up",
)

#: `status_reason` values, all machine-readable so the UI can say what is
#: actually wrong instead of "error".
RECEIPT_REASONS = (
    "not_published", "portal_down", "rate_limited", "captcha", "http_error", "timeout",
    "parser_failed", "key_mismatch", "invalid_dv", "unsupported_uf", "unsupported_host",
    "not_nfce", "homolog", "cancelled_by_sefaz", "needs_qr",
)


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        Index("ix_receipts_due", "status", "next_attempt_at"),
        Index("ix_receipts_store_issued", "store_id", "issued_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_key: Mapped[str] = mapped_column(String(44), unique=True, index=True)
    c_uf: Mapped[str] = mapped_column(String(2))
    uf: Mapped[str] = mapped_column(String(2))
    model: Mapped[str] = mapped_column(String(2), default="65")
    series: Mapped[int] = mapped_column(Integer)
    number: Mapped[int] = mapped_column(Integer)
    tp_amb: Mapped[int] = mapped_column(SmallInteger, default=1)
    tp_emis: Mapped[int] = mapped_column(SmallInteger, default=1)
    qr_version: Mapped[int] = mapped_column(SmallInteger, default=0)
    issuer_cnpj: Mapped[str] = mapped_column(String(14), index=True)
    qr_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    status_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parser_version: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)

    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True
    )
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: `issued_at` as a date in the issuer's local time — what a price
    #: observation is keyed on. Stored, not derived, so the index is plain.
    issued_on: Mapped[Optional[_date]] = mapped_column(Date, nullable=True)
    authorized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    protocol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    items_count: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    products_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    discount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    addition: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    shipping: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    total: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    approx_taxes: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    payments: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    #: SHA-256 over salt + digits. Never the CPF.
    customer_cpf_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: Filled by the price service once the catalogue exists; the shape is
    #: its to define. Persisted so the screen does not recompute it.
    variation_summary: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    raw_html: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    raw_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    first_scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    store: Mapped[Optional["Store"]] = relationship(lazy="selectin")
    items: Mapped[list["ReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", lazy="selectin",
        order_by="ReceiptItem.ordinal",
    )
    links: Mapped[list["ReceiptLink"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", lazy="selectin"
    )


class ReceiptItem(Base):
    __tablename__ = "receipt_items"
    __table_args__ = (
        UniqueConstraint("receipt_id", "ordinal", name="uq_receipt_items_receipt_ordinal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(SmallInteger)
    product_code: Mapped[str] = mapped_column(String(60))
    gtin: Mapped[Optional[str]] = mapped_column(String(14), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(200))
    ncm: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    cfop: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    unit: Mapped[str] = mapped_column(String(6))
    # Four decimals on quantity and unit price: scales and fuel pumps use them.
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4))
    total: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    #: A human correction. The printed figure stays in `unit_price`.
    unit_price_corrected: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4), nullable=True)
    corrected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    receipt: Mapped["Receipt"] = relationship(back_populates="items")

    @property
    def effective_unit_price(self) -> Decimal:
        return self.unit_price_corrected if self.unit_price_corrected is not None else self.unit_price


class ReceiptLink(Base):
    __tablename__ = "receipt_links"
    __table_args__ = (
        UniqueConstraint("receipt_id", "workspace_id", name="uq_receipt_links_receipt_workspace"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    #: Bought for someone else, or by someone else on your card. Leaves your
    #: totals; the price observation stays in the shared history.
    not_my_purchase: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    receipt: Mapped["Receipt"] = relationship(back_populates="links")
    workspace: Mapped["Workspace"] = relationship()
    user: Mapped["User"] = relationship()
    transaction: Mapped[Optional["Transaction"]] = relationship()
