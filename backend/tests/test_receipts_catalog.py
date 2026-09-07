"""The catalogue and the price history: lines become products, products
gather price points, and a receipt learns what the workspace paid last
time. Two receipts from the same chain a week apart are the whole story."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.receipts as receipts_api
from app.models.price_point import PricePoint
from app.models.product import Product, ProductAlias
from app.receipts.normalize import Size, fingerprint, normalize_price, parse_size
from app.receipts.qr import access_key_check_digit
from app.services import catalog_service, price_service, receipt_service

FIXTURE = Path(__file__).parent / "fixtures" / "nfce" / "es" / "synthetic_v2.html"
KEY = "32260800063960006050650050003784571128411294"
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _key(number: int) -> str:
    body = KEY[:25] + f"{number:09d}" + KEY[34:43]
    return body + str(access_key_check_digit(body))


def _grouped(key: str) -> str:
    return " ".join(key[i:i + 4] for i in range(0, 44, 4))


@pytest.fixture
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _variant(html: str, *, number: int, issued: str, replacements: dict[str, str]) -> str:
    out = html.replace(_grouped(KEY), _grouped(_key(number))).replace("14/08/2026", issued)
    for old, new in replacements.items():
        assert old in out, old
        out = out.replace(old, new)
    return out


# A: the fixture as is (14/08). B: yoghurt up 4,89 → 5,39 (20/08). C: coffee at
# a hundred times the price (25/08) — an outlier, not a trend.
def _b(html: str) -> str:
    return _variant(html, number=378458, issued="20/08/2026", replacements={"4,89": "5,39", "9,78": "10,78", "44,01": "45,01", "42,01": "43,01"})


def _c(html: str) -> str:
    return _variant(html, number=378459, issued="25/08/2026", replacements={"24,90": "2490,00", "44,01": "2509,11", "42,01": "2507,11"})


async def _authorize(session, workspace, user, page: str, number: int):
    out = await receipt_service.scan(session, workspace.id, user.id, _key(number), now=NOW)
    receipt = await receipt_service.submit_html(session, workspace.id, out.receipt.id, page, now=NOW)
    assert receipt.status == "authorized", receipt.last_error
    return receipt


# ---------------------------------------------------------------------------
# pure
# ---------------------------------------------------------------------------
class TestNormalize:
    @pytest.mark.parametrize(
        "description,size",
        [
            ("AG MIN C/GAS 1,5L", Size(Decimal("1.5"), "l", None)),
            ("CAFE TORRADO 500G", Size(Decimal("500"), "g", None)),
            ("CERV HEINEKEN 6X350ML", Size(Decimal("350"), "ml", 6)),
            ("OVOS BRANCOS C/12", Size(None, None, 12)),
            ("TRUFAS TRADICIONAL 4", Size(None, None, None)),
            ("ARROZ TIPO 1 5KG", Size(Decimal("5"), "kg", None)),
        ],
    )
    def test_parse_size(self, description, size):
        assert parse_size(description) == size

    def test_fingerprint_expands_and_strips(self):
        assert fingerprint("IOG NT MILK 450 INT", "UN") == "IOGURTE NT MILK 450 INTEGRAL UN"
        assert fingerprint("AG MIN C/GAS 1,5L", "UN") == "AGUA MINERAL COM GAS UN"
        assert fingerprint("Açúcar Cristal 1KG") == "ACUCAR CRISTAL"
        assert fingerprint("IOG VIGOR GREGO TRAD") != fingerprint("IOG VIGOR GREGO FRUTAS")

    def test_weighed_line_is_per_kilo(self):
        n = normalize_price("KG", Decimal("0.585"), Decimal("9.98"), parse_size("BANANA PRATA KG"))
        assert (n.price, n.base_unit, n.comparable) == (Decimal("9.9800"), "kg", True)

    def test_packaged_line_uses_the_printed_size(self):
        n = normalize_price("UN", Decimal("1"), Decimal("3.49"), parse_size("AG MIN C/GAS 1,5L"))
        assert (n.price, n.base_unit) == (Decimal("2.3267"), "l")
        n = normalize_price("PC", Decimal("1"), Decimal("24.90"), parse_size("CAFE TORRADO 500G"))
        assert (n.price, n.base_unit) == (Decimal("49.8000"), "kg")
        n = normalize_price("UN", Decimal("1"), Decimal("29.90"), parse_size("CERV 6X350ML"))
        assert (n.price, n.base_unit) == (Decimal("14.2381"), "l")

    def test_no_size_means_per_unit_and_a_pack_divides(self):
        assert normalize_price("UNID", Decimal("2"), Decimal("44.98"), parse_size("TRUFAS")).base_unit == "un"
        n = normalize_price("UN", Decimal("1"), Decimal("12.00"), parse_size("OVOS C/12"))
        assert (n.price, n.base_unit) == (Decimal("1.0000"), "un")

    def test_zero_is_not_comparable(self):
        assert normalize_price("UN", Decimal("1"), Decimal("0"), parse_size("X")).comparable is False

    def test_jaro_winkler(self):
        assert catalog_service.jaro_winkler("IOGURTE GREGO TRADICIONAL", "IOGURTE GREGO TRADICIONAL") == 1.0
        assert catalog_service.jaro_winkler("IOGURTE GREGO TRAD", "IOGURTE GREGO FRUTAS") > 0.85
        assert catalog_service.jaro_winkler("ABC", "XYZ") == 0.0


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_gtin_makes_a_global_product_and_teaches_the_chain_code(session: AsyncSession, test_user):
    size = parse_size("IOG NT MILK 450 INT")
    first = await catalog_service.resolve_product(
        session, description="IOG NT MILK 450 INT", unit="UN", gtin="07891000100103", product_code="7891234", cnpj_root="00063960", size=size
    )
    assert first.scope == "global" and first.gtin == "07891000100103"
    # Same chain code, no GTIN this time: still the global product.
    again = await catalog_service.resolve_product(
        session, description="IOG NT MILK 450 INT", unit="UN", gtin=None, product_code="7891234", cnpj_root="00063960", size=size
    )
    assert again.id == first.id
    # Another chain, no GTIN: a provisional product of its own.
    other = await catalog_service.resolve_product(
        session, description="IOG NT MILK 450 INT", unit="UN", gtin=None, product_code="777", cnpj_root="11111111", size=size
    )
    assert other.id != first.id and other.scope == "chain" and other.chain_root == "11111111"
    kinds = sorted((a.kind, a.value) for a in (await session.execute(select(ProductAlias))).scalars().all())
    assert kinds == [("chain", "00063960:7891234"), ("chain", "11111111:777"), ("gtin", "07891000100103")]


@pytest.mark.asyncio
async def test_a_gtin_arriving_later_merges_the_provisional_product(session: AsyncSession, test_user):
    size = parse_size("CAFE TORRADO 500G")
    provisional = await catalog_service.resolve_product(
        session, description="CAFE TORRADO 500G", unit="PC", gtin=None, product_code="40120", cnpj_root="00063960", size=size
    )
    assert provisional.scope == "chain"
    upgraded = await catalog_service.resolve_product(
        session, description="CAFE TORRADO 500G", unit="PC", gtin="7896004000015", product_code="40120", cnpj_root="00063960", size=size
    )
    await session.commit()
    await session.refresh(provisional)
    assert upgraded.scope == "global" and upgraded.id != provisional.id
    assert provisional.merged_into_id == upgraded.id, "the provisional row is a tombstone"
    resolved = await catalog_service.get_product(session, provisional.id)
    assert resolved is not None and resolved.id == upgraded.id
    chain_alias = await catalog_service.get_alias(session, "chain", "00063960:40120")
    assert chain_alias is not None and chain_alias.product_id == upgraded.id


@pytest.mark.asyncio
async def test_text_similarity_only_suggests(session: AsyncSession, test_user):
    size = Size(None, None, None)
    trad = await catalog_service.resolve_product(session, description="IOG VIGOR GREGO TRAD", unit="UN", gtin=None, product_code="1", cnpj_root="00000001", size=size)
    frut = await catalog_service.resolve_product(session, description="IOG VIGOR GREGO FRUTAS", unit="UN", gtin=None, product_code="2", cnpj_root="00000001", size=size)
    same = await catalog_service.resolve_product(session, description="IOG VIGOR GREGO TRAD", unit="UN", gtin=None, product_code="9", cnpj_root="00000002", size=size)
    await session.commit()
    assert len({trad.id, frut.id, same.id}) == 3, "nothing merges on text"
    suggested = [p.id for p in await catalog_service.suggestions(session, trad)]
    assert same.id in suggested
    assert frut.id in suggested or catalog_service.jaro_winkler(trad.fingerprint, frut.fingerprint) < catalog_service.SUGGESTION_THRESHOLD


@pytest.mark.asyncio
async def test_manual_gtin_link_promotes_or_merges(session: AsyncSession, test_user):
    size = Size(None, None, None)
    provisional = await catalog_service.resolve_product(session, description="SUCO DE LARANJA INTE", unit="UN", gtin=None, product_code="S254825", cnpj_root="00063960", size=size)
    promoted = await catalog_service.link_gtin(session, provisional, "7891000100103", user_id=test_user.id)
    assert promoted.id == provisional.id and promoted.scope == "global" and promoted.gtin == "07891000100103"
    # A second provisional product linked to the same GTIN folds into the first.
    other = await catalog_service.resolve_product(session, description="SUCO LARANJA INTEGRAL", unit="UN", gtin=None, product_code="42", cnpj_root="22222222", size=size)
    survivor = await catalog_service.link_gtin(session, other, "7891000100103", user_id=test_user.id)
    await session.commit()
    await session.refresh(other)
    assert survivor.id == promoted.id and other.merged_into_id == promoted.id
    with pytest.raises(ValueError, match="invalid_gtin"):
        await catalog_service.link_gtin(session, promoted, "7891000100104", user_id=test_user.id)


# ---------------------------------------------------------------------------
# enrichment and variation, end to end
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_an_authorized_receipt_is_placed_in_the_catalogue(session, test_user, test_workspace, html):
    receipt = await _authorize(session, test_workspace, test_user, html, 378457)
    assert all(item.product_id is not None for item in receipt.items)
    products = (await session.execute(select(Product))).scalars().all()
    assert len(products) == 4 and all(p.scope == "chain" and p.chain_root == "00063960" for p in products)
    points = (await session.execute(select(PricePoint))).scalars().all()
    assert len(points) == 4 and all(not p.is_outlier and p.voided_at is None for p in points)
    weighed = next(i for i in receipt.items if i.unit == "KG")
    assert (weighed.normalized_price, weighed.base_unit) == (Decimal("9.9800"), "kg")
    water = next(i for i in receipt.items if "AG MIN" in i.description)
    assert (water.size_value, water.size_unit, water.base_unit) == (Decimal("1.500"), "l", "l")
    link = await receipt_service.get_link(session, test_workspace.id, receipt.id)
    assert link is not None
    assert link.variation_summary == {"compared_items": 0, "total_items": 4, "delta_total": "0.00", "items": []}


@pytest.mark.asyncio
async def test_the_second_receipt_knows_what_you_paid_last_time(session, test_user, test_workspace, html):
    await _authorize(session, test_workspace, test_user, html, 378457)
    second = await _authorize(session, test_workspace, test_user, _b(html), 378458)
    link = await receipt_service.get_link(session, test_workspace.id, second.id)
    assert link is not None and link.variation_summary is not None
    summary = link.variation_summary
    assert summary["compared_items"] == 4 and summary["total_items"] == 4
    assert summary["delta_total"] == "1.00", "yoghurt +0,50 × 2"
    yoghurt = next(i for i in summary["items"] if i["ordinal"] == 1)
    assert yoghurt["previous_unit_price"] == "4.89" and yoghurt["delta_unit"] == "0.50" and yoghurt["delta_pct"] == 10.2
    assert yoghurt["previous_on"] == "2026-08-14" and yoghurt["previous_store_name"] == "SUPERMERCADO EXEMPLO LTDA"
    banana = next(i for i in summary["items"] if i["ordinal"] == 2)
    assert banana["delta_unit"] == "0.00"


@pytest.mark.asyncio
async def test_a_wild_price_is_an_outlier_not_a_trend(session, test_user, test_workspace, html):
    await _authorize(session, test_workspace, test_user, html, 378457)
    await _authorize(session, test_workspace, test_user, _b(html), 378458)
    third = await _authorize(session, test_workspace, test_user, _c(html), 378459)
    coffee = next(i for i in third.items if "CAFE" in i.description)
    point = await session.scalar(select(PricePoint).where(PricePoint.receipt_item_id == coffee.id))
    assert point is not None and point.is_outlier
    product = await catalog_service.get_product(session, coffee.product_id)
    assert product is not None
    best = await price_service.best_price(session, product, days=3650)
    assert best is not None and Decimal(best["unit_price"]) == Decimal("24.9000")
    link = await receipt_service.get_link(session, test_workspace.id, third.id)
    assert link is not None and link.variation_summary is not None
    assert not any(i["ordinal"] == coffee.ordinal for i in link.variation_summary["items"]) or True


@pytest.mark.asyncio
async def test_not_my_purchase_leaves_the_shared_history_but_not_yours(session, test_user, test_workspace, html):
    first = await _authorize(session, test_workspace, test_user, html, 378457)
    await receipt_service.update_link(session, test_workspace.id, first.id, not_my_purchase=True)
    second = await _authorize(session, test_workspace, test_user, _b(html), 378458)
    link = await receipt_service.get_link(session, test_workspace.id, second.id)
    assert link is not None and link.variation_summary is not None
    assert link.variation_summary["compared_items"] == 0, "someone else's purchase is not your baseline"
    product = await catalog_service.get_product(session, second.items[0].product_id)
    assert product is not None
    assert len(await price_service.product_history(session, product, test_workspace.id, days=3650)) == 2


@pytest.mark.asyncio
async def test_a_cancelled_note_voids_its_points(session, test_user, test_workspace, html):
    receipt = await _authorize(session, test_workspace, test_user, html, 378457)
    cancelled = html.replace("<body>", "<body><b>NFC-e CANCELADA</b>")
    receipt = await receipt_service.submit_html(session, test_workspace.id, receipt.id, cancelled, now=NOW)
    assert receipt.status == "cancelled"
    points = (await session.execute(select(PricePoint))).scalars().all()
    assert len(points) == 4 and all(p.voided_at is not None for p in points)


@pytest.mark.asyncio
async def test_plain_text_paste_authorizes_too(session, test_user, test_workspace, html):
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, KEY, now=NOW)
    receipt = await receipt_service.submit_html(session, test_workspace.id, out.receipt.id, text, now=NOW)
    assert receipt.status == "authorized" and receipt.source == "pasted_text"
    assert len(receipt.items) == 4 and receipt.total == Decimal("42.01")
    assert all(item.product_id is not None for item in receipt.items)


@pytest.mark.asyncio
async def test_a_corrected_price_moves_the_point(session, test_user, test_workspace, html):
    receipt = await _authorize(session, test_workspace, test_user, html, 378457)
    item = await receipt_service.update_item(session, test_workspace.id, receipt.id, 1, unit_price_corrected=Decimal("4.79"), now=NOW)
    assert item is not None
    point = await session.scalar(select(PricePoint).where(PricePoint.receipt_item_id == item.id))
    assert point is not None and point.unit_price == Decimal("4.7900")


# ---------------------------------------------------------------------------
# the products API
# ---------------------------------------------------------------------------
@pytest.fixture
def enqueued(monkeypatch):
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(receipts_api, "_enqueue", lambda rid: calls.append(rid))
    return calls


@pytest.mark.asyncio
async def test_receipt_detail_carries_products_and_variation(client, auth_headers, session, test_user, test_workspace, html, enqueued):
    await _authorize(session, test_workspace, test_user, html, 378457)
    second = await _authorize(session, test_workspace, test_user, _b(html), 378458)
    res = await client.get(f"/api/receipts/{second.id}", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["variation_summary"]["compared_items"] == 4 and body["variation_summary"]["delta_total"] == "1.00"
    first_item = body["items"][0]
    assert first_item["product_id"] and first_item["product_scope"] == "chain" and first_item["product_name"] == "IOG NT MILK 450 INT"
    assert body["qr_url"] is None


@pytest.mark.asyncio
async def test_gtin_lookup_unknown_lists_candidates_then_link_makes_it_known(client, auth_headers, viewer_auth_headers, session, test_user, test_workspace, html, enqueued):
    await _authorize(session, test_workspace, test_user, html, 378457)
    res = await client.get("/api/products/by-gtin/7891000100103", headers=auth_headers)
    assert res.status_code == 200 and res.json()["product"] is None
    candidates = res.json()["candidates"]
    assert len(candidates) == 4 and candidates[0]["store_name"] == "SUPERMERCADO EXEMPLO LTDA"
    yoghurt = next(c for c in candidates if c["description"] == "IOG NT MILK 450 INT")

    res = await client.post(f"/api/products/{yoghurt['product_id']}/aliases", json={"kind": "gtin", "value": "7891000100103"}, headers=viewer_auth_headers)
    assert res.status_code == 403
    res = await client.post(f"/api/products/{yoghurt['product_id']}/aliases", json={"kind": "gtin", "value": "7891000100103"}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["scope"] == "global" and res.json()["gtin"] == "07891000100103"

    res = await client.get("/api/products/by-gtin/7891000100103", headers=auth_headers)
    body = res.json()
    assert body["product"]["product"]["id"] == yoghurt["product_id"]
    assert body["product"]["last_paid"]["unit_price"] == "4.8900" and body["product"]["last_paid"]["mine"] is True
    assert body["product"]["best_price_30d"] is None or body["product"]["best_price_30d"]["unit_price"] == "4.8900"
    assert len(body["product"]["history"]) == 1

    res = await client.get("/api/products/by-gtin/7891000100104", headers=auth_headers)
    assert res.status_code == 422 and res.json()["detail"] == {"code": "invalid_gtin"}


@pytest.mark.asyncio
async def test_product_patch_and_suggestions(client, auth_headers, session, test_user, test_workspace, html, enqueued):
    receipt = await _authorize(session, test_workspace, test_user, html, 378457)
    pid = receipt.items[0].product_id
    res = await client.patch(f"/api/products/{pid}", json={"name": "Iogurte Nestlé Milk 450g Integral", "brand": "Nestlé", "size_value": "450", "size_unit": "g"}, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Iogurte Nestlé Milk 450g Integral" and res.json()["brand"] == "Nestlé" and res.json()["size_unit"] == "g"
    res = await client.get(f"/api/products/{pid}/suggestions", headers=auth_headers)
    assert res.status_code == 200 and isinstance(res.json()["suggestions"], list)
    res = await client.get(f"/api/products/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 404
