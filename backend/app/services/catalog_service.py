"""The catalogue: which product a receipt line is, and how two products
turn out to be one.

Three identity levels, strongest first, exactly as the design says:

  A. `gtin:<GTIN-14>`            — global, comparable across any store
  B. `chain:<cnpj root>:<code>`  — the chain's own code; comparable
                                   within the chain, and upgraded to A
                                   the first time a GTIN appears next to it
  C. `text:<fingerprint>`        — never resolves; only lists candidates
                                   for a human to confirm

The only automatic merge is B→A when a line carries both a GTIN and a
chain code that already names a provisional product: two hard
identifiers on one line. Text similarity never merges anything on its
own — `IOG VIGOR GREGO TRAD` and `IOG VIGOR GREGO FRUTAS` are 0.95
similar and different products.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_point import PricePoint
from app.models.product import Product, ProductAlias, chain_key
from app.models.receipt import ReceiptItem
from app.receipts.gtin import normalize_gtin
from app.receipts.normalize import ABBREV_VERSION, Size, fingerprint

SUGGESTION_THRESHOLD = 0.92


async def get_alias(session: AsyncSession, kind: str, value: str) -> Optional[ProductAlias]:
    return await session.scalar(
        select(ProductAlias).where(ProductAlias.kind == kind, ProductAlias.value == value)
    )


async def get_product(session: AsyncSession, product_id: uuid.UUID) -> Optional[Product]:
    """Follows tombstones: a merged product answers as its survivor."""
    product = await session.get(Product, product_id)
    hops = 0
    while product is not None and product.merged_into_id is not None and hops < 10:
        product = await session.get(Product, product.merged_into_id)
        hops += 1
    return product


async def product_by_gtin(session: AsyncSession, raw_gtin: str) -> Optional[Product]:
    gtin = normalize_gtin(raw_gtin)
    if gtin is None:
        return None
    alias = await get_alias(session, "gtin", gtin)
    if alias is not None:
        return await get_product(session, alias.product_id)
    return await session.scalar(select(Product).where(Product.gtin == gtin))


async def resolve_product(
    session: AsyncSession,
    *,
    description: str,
    unit: str,
    gtin: Optional[str],
    product_code: str,
    cnpj_root: str,
    size: Size,
) -> Product:
    """Steps 1–5 of the design's matching algorithm, for one line."""
    key = chain_key(cnpj_root, product_code)
    fp = fingerprint(description, unit)
    product: Optional[Product] = None

    if gtin:
        alias = await get_alias(session, "gtin", gtin)
        if alias is not None:
            product = await get_product(session, alias.product_id)
        if product is None:
            product = await session.scalar(select(Product).where(Product.gtin == gtin))
        if product is None:
            product = _new_product(description, fp, size, gtin=gtin, chain_root=None)
            session.add(product)
            await session.flush()
            session.add(ProductAlias(product_id=product.id, kind="gtin", value=gtin, origin="sefaz"))
        chain_alias = await get_alias(session, "chain", key)
        if chain_alias is None:
            session.add(ProductAlias(product_id=product.id, kind="chain", value=key, origin="sefaz"))
        elif chain_alias.product_id != product.id:
            other = await get_product(session, chain_alias.product_id)
            if other is not None and other.id != product.id and other.gtin is None:
                # The one automatic merge: the chain code already named a
                # provisional product, and a GTIN just arrived on the same line.
                await merge_products(session, loser=other, winner=product)
            else:
                # Two global products behind one chain code: the chain reused
                # the code. The newest observation wins the alias; nothing merges.
                chain_alias.product_id = product.id
    else:
        alias = await get_alias(session, "chain", key)
        if alias is not None:
            product = await get_product(session, alias.product_id)
        if product is None:
            product = _new_product(description, fp, size, gtin=None, chain_root=cnpj_root)
            session.add(product)
            await session.flush()
            session.add(ProductAlias(product_id=product.id, kind="chain", value=key, origin="sefaz"))

    _refresh_name(product, description, fp, size)
    await session.flush()
    return product


def _new_product(description: str, fp: str, size: Size, *, gtin: Optional[str], chain_root: Optional[str]) -> Product:
    return Product(
        name=description.strip(),
        gtin=gtin,
        chain_root=chain_root,
        fingerprint=fp,
        fingerprint_version=ABBREV_VERSION,
        size_value=size.value,
        size_unit=size.unit,
        pack_count=size.pack_count,
    )


def _refresh_name(product: Product, description: str, fp: str, size: Size) -> None:
    """A longer description of the same product is a better name: portals
    truncate at 20–30 characters, and some truncate less than others."""
    candidate = description.strip()
    if len(candidate) > len(product.name):
        product.name = candidate
        product.fingerprint = fp
        product.fingerprint_version = ABBREV_VERSION
    if product.size_value is None and size.value is not None:
        product.size_value, product.size_unit = size.value, size.unit
    if product.pack_count is None and size.pack_count is not None:
        product.pack_count = size.pack_count


async def merge_products(session: AsyncSession, *, loser: Product, winner: Product) -> Product:
    """Fold `loser` into `winner`: aliases, receipt lines and price points
    move over; missing attributes are copied; the loser becomes a
    tombstone pointing at the winner. One transaction, caller commits."""
    if loser.id == winner.id:
        return winner
    for stmt in (
        update(ProductAlias).where(ProductAlias.product_id == loser.id).values(product_id=winner.id),
        update(ReceiptItem).where(ReceiptItem.product_id == loser.id).values(product_id=winner.id),
        update(PricePoint).where(PricePoint.product_id == loser.id).values(product_id=winner.id),
        update(Product).where(Product.merged_into_id == loser.id).values(merged_into_id=winner.id),
    ):
        # "fetch" keeps objects already loaded in this session (an alias the
        # matcher just read, an item being enriched) in step with the row.
        await session.execute(stmt.execution_options(synchronize_session="fetch"))
    if winner.brand is None:
        winner.brand = loser.brand
    if winner.category is None:
        winner.category = loser.category
    if winner.size_value is None:
        winner.size_value, winner.size_unit = loser.size_value, loser.size_unit
    if winner.pack_count is None:
        winner.pack_count = loser.pack_count
    if winner.chain_root is None:
        winner.chain_root = loser.chain_root
    if len(loser.name) > len(winner.name):
        winner.name = loser.name
    loser.merged_into_id = winner.id
    await session.flush()
    await session.refresh(winner)
    return winner


async def link_gtin(
    session: AsyncSession, product: Product, raw_gtin: str, *, user_id: Optional[uuid.UUID]
) -> Product:
    """A person scanned a barcode and said "this is that item": the
    provisional product gains the GTIN and becomes global. If a global
    product with that GTIN already exists, the two are one."""
    gtin = normalize_gtin(raw_gtin)
    if gtin is None:
        raise ValueError("invalid_gtin")
    existing = await product_by_gtin(session, gtin)
    if existing is not None and existing.id != product.id:
        return await merge_products(session, loser=product, winner=existing)
    if product.gtin is None:
        product.gtin = gtin
    if await get_alias(session, "gtin", gtin) is None:
        session.add(
            ProductAlias(product_id=product.id, kind="gtin", value=gtin, origin="scan", created_by_user_id=user_id)
        )
    await session.flush()
    return product


async def suggestions(session: AsyncSession, product: Product, *, limit: int = 10) -> list[Product]:
    """Level C: products that *look like* this one, for a person to confirm.
    Same size when both know it; never the product itself or a tombstone."""
    head = product.fingerprint.split(" ")[0] if product.fingerprint else ""
    stmt = select(Product).where(Product.id != product.id, Product.merged_into_id.is_(None))
    if head:
        stmt = stmt.where(Product.fingerprint.like(f"{head[:3]}%"))
    candidates = (await session.execute(stmt.limit(500))).scalars().all()
    scored: list[tuple[float, Product]] = []
    for other in candidates:
        if product.size_value is not None and other.size_value is not None:
            if (product.size_value, product.size_unit) != (other.size_value, other.size_unit):
                continue
        score = 1.0 if other.fingerprint == product.fingerprint else jaro_winkler(product.fingerprint, other.fingerprint)
        if score >= SUGGESTION_THRESHOLD:
            scored.append((score, other))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [other for _, other in scored[:limit]]


async def update_product(
    session: AsyncSession,
    product: Product,
    *,
    name: Optional[str] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
    size_value: Optional[Decimal] = None,
    size_unit: Optional[str] = None,
    pack_count: Optional[int] = None,
) -> Product:
    if name is not None:
        product.name = name.strip()
        product.fingerprint = fingerprint(product.name)
        product.fingerprint_version = ABBREV_VERSION
    if brand is not None:
        product.brand = brand.strip() or None
    if category is not None:
        product.category = category.strip() or None
    if size_value is not None:
        product.size_value = size_value
    if size_unit is not None:
        product.size_unit = size_unit.strip().lower() or None
    if pack_count is not None:
        product.pack_count = pack_count
    await session.flush()
    return product


async def count_receipt_lines(session: AsyncSession, product_id: uuid.UUID) -> int:
    result = await session.execute(
        update(ReceiptItem).where(ReceiptItem.product_id == product_id).values(product_id=product_id)
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult, result).rowcount


def jaro_winkler(a: str, b: str) -> float:
    """Plain Jaro–Winkler, enough for short upper-case strings."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    window = max(len(a), len(b)) // 2 - 1
    a_flags = [False] * len(a)
    b_flags = [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        lo, hi = max(0, i - window), min(len(b), i + window + 1)
        for j in range(lo, hi):
            if not b_flags[j] and b[j] == ca:
                a_flags[i] = b_flags[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    a_m = [ca for i, ca in enumerate(a) if a_flags[i]]
    b_m = [cb for j, cb in enumerate(b) if b_flags[j]]
    transpositions = sum(1 for x, y in zip(a_m, b_m) if x != y) / 2
    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)
