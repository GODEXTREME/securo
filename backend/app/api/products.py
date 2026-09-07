import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace, current_writable_workspace
from app.models.product import Product
from app.receipts.gtin import normalize_gtin
from app.schemas.product import (
    AliasCreate,
    CandidateItemRead,
    GtinLookupRead,
    ProductDetailRead,
    ProductRead,
    ProductUpdate,
    SuggestionsRead,
    point_read,
)
from app.services import catalog_service, price_service

router = APIRouter(prefix="/api/products", tags=["products"])


async def _detail(session: AsyncSession, product: Product, workspace_id: uuid.UUID, days: int) -> ProductDetailRead:
    last = await price_service.last_paid(session, product, workspace_id)
    best = await price_service.best_price(session, product)
    history = await price_service.product_history(session, product, workspace_id, days=days)
    return ProductDetailRead(
        product=ProductRead.of(product),
        last_paid=point_read(last) if last else None,
        best_price_30d=point_read(best) if best else None,
        history=[point_read(p) for p in history],
    )


async def _load(session: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await catalog_service.get_product(session, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get("/by-gtin/{gtin}", response_model=GtinLookupRead)
async def lookup_by_gtin(
    gtin: str,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """The barcode scanner's question. Known GTIN → the product with what
    you paid last and where it was cheapest. Unknown → your recent lines
    without a barcode, so you can say which one this is."""
    normalized = normalize_gtin(gtin)
    if normalized is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "invalid_gtin"})
    product = await catalog_service.product_by_gtin(session, normalized)
    if product is not None:
        return GtinLookupRead(gtin=normalized, product=await _detail(session, product, ctx.workspace.id, 365))
    rows = await price_service.recent_items_without_gtin(session, ctx.workspace.id)
    candidates = [
        CandidateItemRead(
            receipt_id=receipt.id, receipt_item_id=item.id, ordinal=item.ordinal, description=item.description,
            product_id=item.product_id, product_name=item.product.name if item.product else None,
            store_name=(receipt.store.trade_name or receipt.store.legal_name) if receipt.store else None,
            issued_on=receipt.issued_on, unit_price=item.effective_unit_price,
        )
        for item, receipt in rows
    ]
    return GtinLookupRead(gtin=normalized, product=None, candidates=candidates)


@router.get("/{product_id}", response_model=ProductDetailRead)
async def get_product(
    product_id: uuid.UUID,
    days: int = Query(365, ge=1, le=3650),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    product = await _load(session, product_id)
    return await _detail(session, product, ctx.workspace.id, days)


@router.get("/{product_id}/history", response_model=ProductDetailRead)
async def get_product_history(
    product_id: uuid.UUID,
    days: int = Query(365, ge=1, le=3650),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    product = await _load(session, product_id)
    return await _detail(session, product, ctx.workspace.id, days)


@router.get("/{product_id}/suggestions", response_model=SuggestionsRead)
async def get_suggestions(
    product_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    product = await _load(session, product_id)
    return SuggestionsRead(suggestions=[ProductRead.of(p) for p in await catalog_service.suggestions(session, product)])


@router.post("/{product_id}/aliases", response_model=ProductRead)
async def add_alias(
    product_id: uuid.UUID,
    data: AliasCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """`{kind: "gtin", value}` — a person scanned the barcode and said this
    product is that item. The product becomes global; if a global product
    with that GTIN exists, the two become one and the survivor is returned."""
    product = await _load(session, product_id)
    try:
        survivor = await catalog_service.link_gtin(session, product, data.value, user_id=ctx.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": str(exc)}) from exc
    await session.commit()
    await session.refresh(survivor)
    return ProductRead.of(survivor)


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    product = await _load(session, product_id)
    product = await catalog_service.update_product(
        session, product, name=data.name, brand=data.brand, category=data.category,
        size_value=data.size_value, size_unit=data.size_unit, pack_count=data.pack_count,
    )
    await session.commit()
    await session.refresh(product)
    return ProductRead.of(product)


