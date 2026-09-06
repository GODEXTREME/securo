import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.product import Product


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    gtin: Optional[str] = None
    #: Derived: `global` when a GTIN is known, else `chain`.
    scope: str
    chain_root: Optional[str] = None
    size_value: Optional[Decimal] = None
    size_unit: Optional[str] = None
    pack_count: Optional[int] = None
    image_url: Optional[str] = None
    merged_into_id: Optional[uuid.UUID] = None

    @classmethod
    def of(cls, product: Product) -> "ProductRead":
        return cls(
            id=product.id, name=product.name, brand=product.brand, category=product.category,
            gtin=product.gtin, scope=product.scope, chain_root=product.chain_root,
            size_value=product.size_value, size_unit=product.size_unit, pack_count=product.pack_count,
            image_url=product.image_url, merged_into_id=product.merged_into_id,
        )


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    brand: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    size_value: Optional[Decimal] = Field(default=None, ge=0)
    size_unit: Optional[str] = Field(default=None, max_length=4)
    pack_count: Optional[int] = Field(default=None, ge=1, le=999)


class AliasCreate(BaseModel):
    kind: str = Field(pattern=r"^gtin$")
    value: str = Field(min_length=8, max_length=20)


class PricePointRead(BaseModel):
    observed_on: date
    store_id: uuid.UUID
    store_name: Optional[str] = None
    unit: str
    quantity: Decimal
    unit_price: Decimal
    normalized_price: Optional[Decimal] = None
    base_unit: Optional[str] = None
    is_outlier: bool
    source: str
    mine: bool


class ProductDetailRead(BaseModel):
    product: ProductRead
    last_paid: Optional[PricePointRead] = None
    best_price_30d: Optional[PricePointRead] = None
    history: list[PricePointRead] = Field(default_factory=list)


class CandidateItemRead(BaseModel):
    """A recent line of this workspace whose product has no GTIN yet — what
    "you already bought this? pick the line" lists."""
    receipt_id: uuid.UUID
    receipt_item_id: uuid.UUID
    ordinal: int
    description: str
    product_id: Optional[uuid.UUID] = None
    product_name: Optional[str] = None
    store_name: Optional[str] = None
    issued_on: Optional[date] = None
    unit_price: Decimal


class GtinLookupRead(BaseModel):
    gtin: str
    product: Optional[ProductDetailRead] = None
    #: Only filled when `product` is None.
    candidates: list[CandidateItemRead] = Field(default_factory=list)


class SuggestionsRead(BaseModel):
    suggestions: list[ProductRead]


def point_read(raw: dict[str, Any]) -> PricePointRead:
    return PricePointRead(**raw)
