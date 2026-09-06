"""The one shape every state adapter must produce.

A portal's HTML is whatever that state decided; this is what the rest of
the system reads. Validation lives on the model and not in the adapters,
so an adapter that produces an inconsistent receipt fails here, with a
stable code the service turns into `parse_error` — never in production
against a total that does not add up.

Two arithmetic identities are enforced, both from the DANFE itself:

    Σ item.total            ≈ totals.products_total    (±0,01 per line)
    products_total − discount + addition + shipping = totals.total  (±0,01)

Rounding on the portal is per line, which is where the per-line tolerance
comes from. Anything looser would let a dropped item through.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.receipts.gtin import normalize_gtin

ZERO = Decimal("0")
CENT = Decimal("0.01")


class Issuer(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    cnpj: str = Field(min_length=14, max_length=14, pattern=r"^\d{14}$")
    ie: Optional[str] = None
    legal_name: str
    trade_name: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    uf: Optional[str] = None
    zip: Optional[str] = None


class Totals(BaseModel):
    items_count: int = Field(ge=0)
    products_total: Decimal
    discount: Decimal = ZERO
    addition: Decimal = ZERO
    shipping: Decimal = ZERO
    total: Decimal
    approx_taxes: Optional[Decimal] = None


class Payment(BaseModel):
    #: `credit_card`, `debit_card`, `cash`, `pix`, `meal_voucher`,
    #: `food_voucher`, `store_credit`, `other` — the portal's label is kept
    #: in `label` so nothing is lost when the mapping does not know it.
    type: str
    label: Optional[str] = None
    brand: Optional[str] = None
    amount: Decimal
    change: Decimal = ZERO


class CanonicalItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ordinal: int = Field(ge=1)
    product_code: str = Field(min_length=1, max_length=60)
    gtin: Optional[str] = None
    description: str = Field(min_length=1, max_length=200)
    ncm: Optional[str] = None
    cfop: Optional[str] = None
    unit: str = Field(min_length=1, max_length=6)
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    discount: Decimal = ZERO

    @field_validator("gtin", mode="before")
    @classmethod
    def _normalise_gtin(cls, value: object) -> Optional[str]:
        return normalize_gtin(value) if isinstance(value, str) else None

    @field_validator("unit", mode="before")
    @classmethod
    def _upper_unit(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class CanonicalReceipt(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    access_key: str = Field(pattern=r"^\d{44}$")
    uf: str = Field(min_length=2, max_length=2)
    tp_amb: int = 1
    model: str = "65"
    series: int
    number: int
    issued_at: Optional[datetime] = None
    protocol: Optional[str] = None
    authorized_at: Optional[datetime] = None
    issuer: Issuer
    #: Digits only, or None. Hashed by the service before it is stored;
    #: it never reaches the database in the clear.
    customer_cpf: Optional[str] = None
    totals: Totals
    payments: list[Payment] = Field(default_factory=list)
    items: list[CanonicalItem]
    #: `sefaz_html` (fetched), `pasted_html` (user-supplied); later
    #: `dfe_xml`, `ocr`. Confidence follows the source downstream.
    source: str = "sefaz_html"

    @model_validator(mode="after")
    def _arithmetic_holds(self) -> "CanonicalReceipt":
        if len(self.items) != self.totals.items_count:
            raise ValueError(
                f"items_count_mismatch: {len(self.items)} items, header says {self.totals.items_count}"
            )
        ordinals = [item.ordinal for item in self.items]
        if ordinals != list(range(1, len(self.items) + 1)):
            raise ValueError("items_not_sequential")
        items_sum = sum((item.total for item in self.items), ZERO)
        tolerance = CENT * (len(self.items) + 1)
        if abs(items_sum - self.totals.products_total) > tolerance:
            raise ValueError(
                f"products_total_mismatch: items sum {items_sum}, header {self.totals.products_total}"
            )
        expected = (
            self.totals.products_total - self.totals.discount
            + self.totals.addition + self.totals.shipping
        )
        if abs(expected - self.totals.total) > CENT:
            raise ValueError(f"total_mismatch: computed {expected}, header {self.totals.total}")
        return self
