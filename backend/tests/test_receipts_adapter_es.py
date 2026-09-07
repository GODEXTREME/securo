"""The ES adapter against its fixture. A layout change breaks this file,
not production."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.receipts.adapters.base import FetchedPage, PageKind, ParseError
from app.receipts.adapters.es import EsAdapter
from app.receipts.adapters.registry import adapter_for, supported_ufs
from app.receipts.adapters.tabresult import parse_brl
from app.receipts.canonical import CanonicalItem, CanonicalReceipt, Issuer, Totals
from app.receipts.qr import parse_qr_payload

FIXTURE = Path(__file__).parent / "fixtures" / "nfce" / "es" / "synthetic_v2.html"
KEY = "32260800063960006050650050003784571128411294"


@pytest.fixture
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _page(html: str, status: int = 200) -> FetchedPage:
    return FetchedPage(url="http://app.sefaz.es.gov.br/ConsultaNFCe", status_code=status, html=html, fetched_at=datetime.now(timezone.utc))


class TestParseBrl:
    @pytest.mark.parametrize(
        "raw,expected",
        [("9,78", "9.78"), ("R$ 1.234,56", "1234.56"), ("0,585", "0.585"), ("4", "4"), ("Vl. Unit.: 4,89", "4.89"), ("-2,00", "-2.00"), ("2490,00", "2490.00"), ("12345", "12345")],
    )
    def test_reads_brazilian_numbers(self, raw, expected):
        assert parse_brl(raw) == Decimal(expected)

    def test_nothing_is_none(self):
        assert parse_brl("") is None and parse_brl(None) is None and parse_brl("abc") is None


class TestEsAdapter:
    def test_registered(self):
        assert adapter_for("32") is not None and supported_ufs() == ["ES"]
        assert adapter_for("35") is None

    def test_prefers_the_qr_url(self):
        qr = parse_qr_payload(f"http://app.sefaz.es.gov.br/ConsultaNFCe?p={KEY}|2|1|1|abc")
        assert EsAdapter().consulta_url(qr) == qr.url

    def test_bare_key_asks_by_chnfe(self):
        url = EsAdapter().consulta_url(parse_qr_payload(KEY))
        assert url == f"http://app.sefaz.es.gov.br/ConsultaNFCe?chNFe={KEY}"

    def test_allowed_hosts(self):
        assert EsAdapter().allowed_hosts == frozenset({"app.sefaz.es.gov.br"})

    def test_the_real_portal_answer_is_a_challenge(self):
        """The one page from this portal we have actually seen. It must be
        CAPTCHA — anything else sends the receipt round the retry schedule
        for nothing."""
        real = (FIXTURE.parent / "turnstile_challenge.html").read_text(encoding="utf-8")
        assert EsAdapter().classify(_page(real)) == PageKind.CAPTCHA

    def test_classify(self, html):
        adapter = EsAdapter()
        assert adapter.classify(_page(html)) == PageKind.AUTHORIZED
        assert adapter.classify(_page("<html>Não foi possível localizar a NFC-e</html>")) == PageKind.NOT_FOUND_YET
        assert adapter.classify(_page("<div class='g-recaptcha'></div>")) == PageKind.CAPTCHA
        assert adapter.classify(_page(html.replace("<body>", "<body><b>NFC-e CANCELADA</b>"))) == PageKind.CANCELLED
        assert adapter.classify(_page("<html>manutenção</html>", 503)) == PageKind.ERROR_PAGE
        assert adapter.classify(_page("<html>something else</html>")) == PageKind.ERROR_PAGE

    def test_parses_the_whole_note(self, html):
        r = EsAdapter().parse(html)
        assert r.access_key == KEY and r.uf == "ES"
        assert (r.number, r.series) == (378457, 5)
        assert r.issued_at == datetime.fromisoformat("2026-08-14T18:32:00-03:00")
        assert r.protocol == "132260045678901"
        assert r.authorized_at == datetime.fromisoformat("2026-08-14T18:32:07-03:00")
        assert r.issuer.cnpj == "00063960006050"
        assert r.issuer.legal_name == "SUPERMERCADO EXEMPLO LTDA"
        assert (r.issuer.street, r.issuer.number, r.issuer.district, r.issuer.city, r.issuer.uf) == (
            "AVENIDA NOSSA SENHORA DA PENHA", "1500", "SANTA LUCIA", "VITORIA", "ES"
        )
        assert r.customer_cpf == "12345678909"
        assert r.totals.items_count == 4
        assert r.totals.products_total == Decimal("44.01")
        assert r.totals.discount == Decimal("2.00")
        assert r.totals.total == Decimal("42.01")
        assert r.totals.approx_taxes == Decimal("6.12")
        assert [(p.type, p.amount, p.change) for p in r.payments] == [
            ("credit_card", Decimal("30.00"), Decimal("0")),
            ("cash", Decimal("15.00"), Decimal("2.99")),
        ]
        assert len(r.items) == 4
        first = r.items[0]
        assert (first.ordinal, first.product_code, first.description) == (1, "7891234", "IOG NT MILK 450 INT")
        assert (first.unit, first.quantity, first.unit_price, first.total) == ("UN", Decimal("2"), Decimal("4.89"), Decimal("9.78"))
        assert first.gtin is None, "the tabResult template never shows the GTIN"
        weighed = r.items[1]
        assert (weighed.unit, weighed.quantity, weighed.unit_price) == ("KG", Decimal("0.585"), Decimal("9.98"))

    def test_sum_of_items_equals_products_total(self, html):
        r = EsAdapter().parse(html)
        assert sum(i.total for i in r.items) == r.totals.products_total
        assert r.totals.products_total - r.totals.discount == r.totals.total

    def test_missing_table_is_layout_changed(self):
        with pytest.raises(ParseError) as exc:
            EsAdapter().parse("<html><body>nothing</body></html>")
        assert exc.value.code == "layout_changed"

    def test_dropped_item_fails_the_arithmetic(self, html):
        broken = html.replace('<tr id="Item + 4">', '<tr id="Item + 4" hidden>', 1)
        # Hiding does not remove; remove the row outright.
        start = html.index('<tr id="Item + 4">')
        end = html.index("</tr>", start) + len("</tr>")
        broken = html[:start] + html[end:]
        with pytest.raises(ParseError) as exc:
            EsAdapter().parse(broken)
        assert exc.value.code == "items_count_mismatch"

    def test_wrong_total_fails_the_arithmetic(self, html):
        broken = html.replace('<span class="totalNumb txtMax">42,01</span>', '<span class="totalNumb txtMax">49,99</span>')
        with pytest.raises(ParseError) as exc:
            EsAdapter().parse(broken)
        assert exc.value.code == "total_mismatch"


REAL = FIXTURE.parent / "32260800063960006050650050003784571128411294.html"


class TestEsRealPage:
    """The page a browser renders after the Turnstile challenge, captured
    2026-09-06 with the consumer's data masked. This is the layout the
    portal actually serves; the synthetic fixture covers the paths this
    particular note does not exercise (discount line, weighed item,
    itemised payments)."""

    def test_classifies_as_authorized(self):
        assert EsAdapter().classify(_page(REAL.read_text(encoding="utf-8"))) == PageKind.AUTHORIZED

    def test_parses_the_note(self):
        r = EsAdapter().parse(REAL.read_text(encoding="utf-8"))
        assert r.access_key == KEY and (r.number, r.series) == (378457, 5)
        assert r.issued_at == datetime.fromisoformat("2026-08-29T11:18:43-03:00")
        assert r.protocol == "232260488249992"
        assert r.issuer.legal_name == "WMB SUPERMERCADOS DO BRASIL LTDA."
        assert (r.issuer.street, r.issuer.number, r.issuer.district, r.issuer.city, r.issuer.uf) == (
            "Av. Mascarenhas de Moraes", "1905", "Bento Ferreira", "Vitoria", "ES"
        ), "the blank complement in the address must not shift the fields"
        assert r.customer_cpf == "12345678909"
        assert [(i.product_code, i.description, i.unit, i.quantity, i.unit_price, i.total) for i in r.items] == [
            ("S259790", "TRUFAS TRADICIONAL 4", "UNID", Decimal("2"), Decimal("44.98"), Decimal("89.96")),
            ("S254825", "SUCO DE LARANJA INTE", "UNID", Decimal("1"), Decimal("15.98"), Decimal("15.98")),
            ("S260353", "HAVAIANAS BRASIL PRE", "UNID", Decimal("1"), Decimal("39.99"), Decimal("39.99")),
        ]

    def test_products_total_is_derived_when_the_portal_omits_it(self):
        r = EsAdapter().parse(REAL.read_text(encoding="utf-8"))
        assert r.totals.items_count == 3
        assert r.totals.products_total == Decimal("145.93") == r.totals.total
        assert r.totals.discount == Decimal("0")
        assert r.totals.approx_taxes == Decimal("79.55")

    def test_a_nan_payment_line_is_tolerated(self):
        assert EsAdapter().parse(REAL.read_text(encoding="utf-8")).payments == []

    def test_view_source_paste_unwraps_to_the_page(self):
        from html import escape

        from app.receipts.pasted import normalize_pasted

        page = REAL.read_text(encoding="utf-8")
        rows = "".join(
            f'<tr><td class="line-number" value="{n}"></td><td class="line-content">{escape(line)}</td></tr>'
            for n, line in enumerate(page.splitlines(), start=1)
        )
        viewer = f"<html><body><table>{rows}</table></body></html>"
        # The viewer escapes the markup, so the DANFE is invisible to classify
        # (the Turnstile markup the page still carries shows through instead).
        assert EsAdapter().classify(_page(viewer)) != PageKind.AUTHORIZED
        unwrapped = normalize_pasted(viewer)
        assert EsAdapter().parse(unwrapped).number == 378457
        assert normalize_pasted(page) == page, "a real page passes through untouched"


class TestCanonicalModel:
    def _receipt(self, items: list[CanonicalItem] | None = None) -> CanonicalReceipt:
        if items is None:
            items = [CanonicalItem(ordinal=1, product_code="1", description="a", unit="UN", quantity=Decimal("2"), unit_price=Decimal("4.89"), total=Decimal("9.78"))]
        return CanonicalReceipt(
            access_key=KEY, uf="ES", series=5, number=1,
            issuer=Issuer(cnpj="00063960006050", legal_name="X"),
            totals=Totals(items_count=1, products_total=Decimal("9.78"), total=Decimal("9.78")),
            items=items,
        )

    def test_valid(self):
        assert self._receipt().totals.total == Decimal("9.78")

    def test_gtin_normalised_on_the_item(self):
        item = CanonicalItem(ordinal=1, product_code="1", gtin="7891000100103", description="a", unit="un", quantity=Decimal(1), unit_price=Decimal(1), total=Decimal(1))
        assert item.gtin == "07891000100103" and item.unit == "UN"

    def test_non_sequential_ordinals(self):
        with pytest.raises(ValueError, match="items_not_sequential"):
            self._receipt(items=[CanonicalItem(ordinal=2, product_code="1", description="a", unit="UN", quantity=Decimal(1), unit_price=Decimal("9.78"), total=Decimal("9.78"))])
