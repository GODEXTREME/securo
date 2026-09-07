"""One price observation per receipt line. Append-only.

Instance-wide and anonymous by construction: a point knows the product,
the store, the receipt and the date — never who bought it. The personal
history is the join with `receipt_links` for a workspace, which is also
what "not my purchase" filters on without touching the shared record.

`is_outlier` keeps a wild point in the history but out of the variation
and best-price answers. `voided_at` is set when the state cancels the
note; the point stays, marked, so a cancelled sale never pretends to be a
price.
"""
import uuid
from datetime import date as _date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.receipt import Receipt, ReceiptItem
    from app.models.store import Store


class PricePoint(Base):
    __tablename__ = "price_points"
    __table_args__ = (
        Index("ix_price_points_product_observed", "product_id", "observed_on"),
        Index("ix_price_points_store_product_observed", "store_id", "product_id", "observed_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    receipt_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receipt_items.id", ondelete="CASCADE"), unique=True
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), index=True
    )
    observed_on: Mapped[_date] = mapped_column(Date)
    unit: Mapped[str] = mapped_column(String(6))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4))
    normalized_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4), nullable=True)
    base_unit: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    comparable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(12), default="sefaz_html")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    product: Mapped["Product"] = relationship()
    store: Mapped["Store"] = relationship()
    receipt: Mapped["Receipt"] = relationship()
    receipt_item: Mapped["ReceiptItem"] = relationship()
