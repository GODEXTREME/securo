import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.receipt import Receipt, ReceiptItem, ReceiptLink


class ScanRequest(BaseModel):
    #: The QR URL, a bare 44-digit key, or pasted text containing either.
    payload: str = Field(min_length=1, max_length=4000)


class StoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cnpj: str
    cnpj_root: str
    legal_name: str
    trade_name: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    uf: Optional[str] = None
    zip: Optional[str] = None


class ReceiptItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordinal: int
    product_code: str
    gtin: Optional[str] = None
    description: str
    ncm: Optional[str] = None
    cfop: Optional[str] = None
    unit: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    discount: Decimal
    unit_price_corrected: Optional[Decimal] = None
    effective_unit_price: Decimal
    # Catalogue. Null until the matcher has run.
    product_id: Optional[uuid.UUID] = None
    product_name: Optional[str] = None
    #: `global` (has a GTIN, comparable anywhere) or `chain` (this chain only).
    product_scope: Optional[str] = None
    normalized_price: Optional[Decimal] = None
    base_unit: Optional[str] = None
    comparable: bool = True


class ReceiptLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    not_my_purchase: bool
    transaction_id: Optional[uuid.UUID] = None
    scanned_at: datetime


class ReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    access_key: str
    uf: str
    series: int
    number: int
    issuer_cnpj: str
    status: str
    status_reason: Optional[str] = None
    attempts: int
    next_attempt_at: Optional[datetime] = None
    #: Free text from the last attempt — the portal's answer, an HTTP or TLS
    #: error, a parser code. What a person needs to tell the states apart.
    last_error: Optional[str] = None
    source: Optional[str] = None
    #: The URL inside the QR, for "open in your browser" on the paste path.
    qr_url: Optional[str] = None
    store: Optional[StoreRead] = None
    issued_at: Optional[datetime] = None
    issued_on: Optional[date] = None
    authorized_at: Optional[datetime] = None
    protocol: Optional[str] = None
    items_count: Optional[int] = None
    products_total: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    addition: Optional[Decimal] = None
    shipping: Optional[Decimal] = None
    total: Optional[Decimal] = None
    approx_taxes: Optional[Decimal] = None
    payments: Optional[Any] = None
    variation_summary: Optional[Any] = None
    first_scanned_at: datetime
    items: list[ReceiptItemRead] = Field(default_factory=list)
    link: ReceiptLinkRead

    @classmethod
    def from_pair(cls, receipt: Receipt, link: ReceiptLink, *, with_items: bool = True) -> "ReceiptRead":
        return cls(
            id=receipt.id,
            access_key=receipt.access_key,
            uf=receipt.uf,
            series=receipt.series,
            number=receipt.number,
            issuer_cnpj=receipt.issuer_cnpj,
            status=receipt.status,
            status_reason=receipt.status_reason,
            attempts=receipt.attempts,
            next_attempt_at=receipt.next_attempt_at,
            last_error=receipt.last_error,
            source=receipt.source,
            qr_url=receipt.qr_url,
            store=StoreRead.model_validate(receipt.store) if receipt.store else None,
            issued_at=receipt.issued_at,
            issued_on=receipt.issued_on,
            authorized_at=receipt.authorized_at,
            protocol=receipt.protocol,
            items_count=receipt.items_count,
            products_total=receipt.products_total,
            discount=receipt.discount,
            addition=receipt.addition,
            shipping=receipt.shipping,
            total=receipt.total,
            approx_taxes=receipt.approx_taxes,
            payments=receipt.payments,
            variation_summary=link.variation_summary,
            first_scanned_at=receipt.first_scanned_at,
            items=[item_read(item) for item in receipt.items] if with_items else [],
            link=ReceiptLinkRead.model_validate(link),
        )


def item_read(item: ReceiptItem) -> ReceiptItemRead:
    return ReceiptItemRead(
        id=item.id,
        ordinal=item.ordinal,
        product_code=item.product_code,
        gtin=item.gtin,
        description=item.description,
        ncm=item.ncm,
        cfop=item.cfop,
        unit=item.unit,
        quantity=item.quantity,
        unit_price=item.unit_price,
        total=item.total,
        discount=item.discount,
        unit_price_corrected=item.unit_price_corrected,
        effective_unit_price=item.effective_unit_price,
        product_id=item.product_id,
        product_name=item.product.name if item.product else None,
        product_scope=item.product.scope if item.product else None,
        normalized_price=item.normalized_price,
        base_unit=item.base_unit,
        comparable=item.comparable,
    )


class ScanResponse(BaseModel):
    receipt: ReceiptRead
    #: The key was new to the instance and has just been queued.
    created: bool
    #: This workspace had already scanned it; the existing note is returned.
    already_linked: bool


class ReceiptLinkUpdate(BaseModel):
    not_my_purchase: Optional[bool] = None
    transaction_id: Optional[uuid.UUID] = None
    #: Explicit, because `transaction_id: None` cannot be told apart from
    #: "not sent" in a PATCH.
    clear_transaction: bool = False


class ReceiptItemUpdate(BaseModel):
    #: None restores the printed price.
    unit_price_corrected: Optional[Decimal] = Field(default=None, ge=0)


class SubmitHtmlRequest(BaseModel):
    html: str = Field(min_length=1, max_length=2_000_000)


class SupportedUfsRead(BaseModel):
    ufs: list[str]
