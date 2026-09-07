"""The catalogue: one row per trade item, and the names it goes by.

Instance-wide, like `stores`: a product is the same product whichever
workspace bought it, and sharing the catalogue is what lets two
workspaces compare prices.

**Scope is derived, never stored.** A product with a GTIN is global —
comparable across any store — and one without is provisional, scoped to
the chain (`chain_root`) whose internal code named it. There is no
`scope` column because a column can disagree with the fact.

Aliases are how a line on a receipt finds its product:

    gtin:<GTIN-14>            global, from the portal or a barcode scan
    chain:<cnpj root>:<code>  the chain's own code; learned from a GTIN
                              when both appear on one line, otherwise
                              the provisional product's only name
    text:<fingerprint>        reserved; never resolves anything by itself

`merged_into_id` is a tombstone: a product folded into another keeps its
row so old links and URLs still resolve, and points at the survivor.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User

ALIAS_KINDS = ("gtin", "chain", "text")
ALIAS_ORIGINS = ("sefaz", "user", "scan", "enrichment")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    gtin: Mapped[Optional[str]] = mapped_column(String(14), unique=True, nullable=True)
    #: Set when the product was born provisional. Kept after it turns global
    #: as a record of where it came from.
    chain_root: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(200), index=True)
    fingerprint_version: Mapped[int] = mapped_column(SmallInteger, default=1)
    size_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    size_unit: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    pack_count: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    enrichment_source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    merged_into_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    aliases: Mapped[list["ProductAlias"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def scope(self) -> str:
        return "global" if self.gtin else "chain"


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_product_aliases_kind_value"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(6))
    value: Mapped[str] = mapped_column(String(120))
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("1.00"))
    origin: Mapped[str] = mapped_column(String(12), default="sefaz")
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    product: Mapped["Product"] = relationship(back_populates="aliases")
    created_by: Mapped[Optional["User"]] = relationship()


def chain_key(cnpj_root: str, product_code: str) -> str:
    return f"{cnpj_root}:{product_code.strip()}"
