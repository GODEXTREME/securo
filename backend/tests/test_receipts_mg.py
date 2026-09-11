"""Minas Gerais (cUF 31).

The state serves its own layout — a JSF page, `infoqrcode.xhtml` — and
reaches it only after a person passes a Cloudflare Turnstile and presses
"Visualizar". Everything here reads the page that comes out of that.
"""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.receipts.adapters.base import FetchedPage, PageKind, ParseError
from app.receipts.adapters.mg import MgAdapter
from app.receipts.adapters.mg_info import parse_mg_info
from app.receipts.qr import parse_qr_payload
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for, current_portal_url

FIXTURES = Path(__file__).parent / "fixtures" / "nfce" / "mg"
KEY = "31260913482024000257650010001805631869078341"
QR = (
    "https://portalsped.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml"
    f"?p={KEY}|2|1|1|54CA4F008CFF4E67B7EB33418830851449FB5392"
)


def page(html: str, url: str = QR, status: int = 200) -> FetchedPage:
    return FetchedPage(url=url, status_code=status, html=html, fetched_at=datetime.now())


@pytest.fixture
def note() -> str:
    return (FIXTURES / f"{KEY}.html").read_text(encoding="utf-8")


class TestTheHostThatAnswers:
    OLD = (
        "https://nfce.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml"
        f"?p={KEY}|2|1|1|54CA4F008CFF4E67B7EB33418830851449FB5392"
    )

    def test_the_portal_is_portalsped(self):
        """`nfce.fazenda.mg.gov.br` does not complete a TLS handshake any
        more; `portalsped` serves the same paths."""
        assert DEFAULT_CONSULTA_URLS["MG"].startswith("https://portalsped.fazenda.mg.gov.br/portalnfce/")

    def test_a_qr_printed_before_the_move_still_resolves(self):
        moved = current_portal_url(self.OLD, "MG")
        assert moved is not None
        assert moved.startswith("https://portalsped.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml?p=")
        # The signature is what the portal checks: losing it turns a
        # readable note into "QR Code Inválido".
        assert moved.endswith("|2|1|1|54CA4F008CFF4E67B7EB33418830851449FB5392")

    def test_both_hosts_stay_allowed(self):
        hosts = allowed_hosts_for("MG")
        assert "portalsped.fazenda.mg.gov.br" in hosts
        assert "nfce.fazenda.mg.gov.br" in hosts


class TestTheUrlItAsksFor:
    def test_the_qr_url_is_preferred_over_the_table(self):
        assert MgAdapter().consulta_url(parse_qr_payload(QR)) == QR

    def test_the_signature_survives_a_rebuild(self):
        """The portal checks it. A URL rebuilt without it reaches the
        challenge-guarded form rather than the note."""
        rebuilt = MgAdapter().consulta_url(replace(parse_qr_payload(QR), url=None))
        assert rebuilt.startswith(f"{DEFAULT_CONSULTA_URLS['MG']}?p={KEY}|2|1|1|")
        assert rebuilt.endswith("54CA4F008CFF4E67B7EB33418830851449FB5392")

    def test_the_key_route_is_known_not_to_answer(self):
        """`consultaarg.xhtml` is a form behind the same challenge, so
        spending a request on it teaches nothing."""
        assert MgAdapter().key_route_answers is False


class TestWhatKindOfPageThisIs:
    def test_the_note_is_recognised_by_its_item_table(self, note):
        assert MgAdapter().classify(page(note)) is PageKind.AUTHORIZED

    def test_the_challenge_is_a_captcha(self):
        """Keyed on the item table and not on the title, because the
        challenge page carries the same heading the note does."""
        challenge = (
            '<html><body><h1>Nota Fiscal de Consumidor Eletrônica -'
            ' Visualização dados qrcode NFC-e</h1>'
            '<div class="cf-turnstile" data-sitekey="0x4AAAAAAAZxv_tC7WhZeETe"></div>'
            "</body></html>"
        )
        assert MgAdapter().classify(page(challenge)) is PageKind.CAPTCHA

    def test_a_portal_that_is_down_is_not_a_missing_note(self):
        assert MgAdapter().classify(page("<html/>", status=503)) is PageKind.ERROR_PAGE


class TestReadingTheNote:
    def test_the_header_facts(self, note):
        receipt = parse_mg_info(note)
        assert receipt.access_key == KEY
        assert receipt.uf == "MG"
        assert receipt.model == "65"
        assert receipt.series == 1
        assert receipt.number == 180563
        assert receipt.issued_at == datetime(2026, 9, 5, 10, 42, 13)
        assert receipt.protocol == "131262171572119"

    def test_the_issuer(self, note):
        issuer = parse_mg_info(note).issuer
        assert issuer.cnpj == "13482024000257"
        assert issuer.ie == "0017567910179"
        assert issuer.legal_name == "COMERCIAL FESTAS E FESTAS LTDA"
        assert issuer.uf == "MG"

    def test_the_address_comes_from_the_one_line_that_has_it(self, note):
        """`AV CRISTIANO MACHADO, 1950, CIDADE NOVA, 3106200 - BELO
        HORIZONTE, MG` — and the IBGE code is not part of the city."""
        issuer = parse_mg_info(note).issuer
        assert issuer.street == "AV CRISTIANO MACHADO"
        assert issuer.number == "1950"
        assert issuer.district == "CIDADE NOVA"
        assert issuer.city == "BELO HORIZONTE"

    def test_the_item(self, note):
        items = parse_mg_info(note).items
        assert len(items) == 1
        item = items[0]
        assert item.ordinal == 1
        assert item.product_code == "2165"
        assert item.description == "SACO MET 40X60 UN"
        assert item.unit == "UN"
        assert item.quantity == Decimal("2")
        assert item.total == Decimal("6.00")

    def test_the_unit_price_is_derived_because_the_page_omits_it(self, note):
        """Two bags for six reais is three reais each; the page says only
        the first two numbers."""
        assert parse_mg_info(note).items[0].unit_price == Decimal("3")

    def test_the_note_carries_no_barcode(self, note):
        """The item names the merchant's own code and nothing global, so
        a product from here stays comparable within its chain until
        somebody scans one."""
        assert parse_mg_info(note).items[0].gtin is None

    def test_the_totals(self, note):
        totals = parse_mg_info(note).totals
        assert totals.items_count == 1
        assert totals.products_total == Decimal("6.00")
        assert totals.total == Decimal("6.00")
        assert totals.discount == Decimal("0")

    def test_the_approximate_taxes_come_out_of_the_free_text(self, note):
        """`Trib aprox R$: 1,29 Fed e 1,08 Est`, which the merchant's own
        software writes into the complementary information."""
        assert parse_mg_info(note).totals.approx_taxes == Decimal("2.37")

    def test_the_payment(self, note):
        payments = parse_mg_info(note).payments
        assert len(payments) == 1
        assert payments[0].type == "debit_card"
        assert payments[0].label == "04 - Cartão de Débito"
        assert payments[0].amount == Decimal("6.00")

    def test_this_page_never_names_a_consumer(self, note):
        """Its consumer panel has room for a name and a state and no CPF
        at all, and on this note even those are empty."""
        assert parse_mg_info(note).customer_cpf is None


class TestTheTwoNumberFormats:
    """The item table prints `R$ 6,00` and the summary rows print `6.00`.
    Reading either with the other's rules loses money quietly, so both
    are exercised with a value where the two disagree.
    """

    def test_cents_in_a_summary_row_survive(self, note):
        html = note.replace("<strong>6.00</strong>", "<strong>6.50</strong>").replace(
            "Valor total R$: R$ 6,00", "Valor total R$: R$ 6,50"
        )
        receipt = parse_mg_info(html)
        assert receipt.totals.total == Decimal("6.50")
        assert receipt.items[0].total == Decimal("6.50")

    def test_a_thousands_separator_in_an_item_survives(self, note):
        html = note.replace("<strong>6.00</strong>", "<strong>1234.56</strong>").replace(
            "Valor total R$: R$ 6,00", "Valor total R$: R$ 1.234,56"
        )
        receipt = parse_mg_info(html)
        assert receipt.items[0].total == Decimal("1234.56")
        assert receipt.totals.products_total == Decimal("1234.56")


class TestWhenThePageIsNotWhatWeThought:
    def test_a_page_with_no_item_table_is_refused(self, note):
        html = note.replace('id="myTable"', 'id="somethingElse"')
        with pytest.raises(ParseError) as raised:
            parse_mg_info(html)
        assert raised.value.code == "layout_changed"

    def test_an_item_without_a_product_code_is_refused(self, note):
        html = note.replace("(Código: 2165)", "")
        with pytest.raises(ParseError) as raised:
            parse_mg_info(html)
        assert raised.value.code == "layout_changed"

    def test_a_total_that_does_not_match_the_items_is_refused(self, note):
        """The arithmetic the canonical model insists on is the backstop
        for every reading mistake above it."""
        html = note.replace("<strong>6.00</strong>", "<strong>9.00</strong>")
        with pytest.raises(Exception) as raised:
            parse_mg_info(html)
        assert "products_total_mismatch" in str(raised.value)
