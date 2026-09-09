"""Goiás: the state whose barcode is one page further in.

The QR leads to a consumer DANFE like everyone else's. What makes this
adapter worth having is the page *after* it — the national detailed view
— because that one prints `Código EAN Comercial`, and the consumer
template never does.
"""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.receipts.adapters.base import FetchedPage, PageKind, ParseError
from app.receipts.adapters.go import DETAIL_PATH, GoAdapter
from app.receipts.qr import parse_qr_payload

KEY = "52260920758851004607650020000419021267999864"
SIG = "91D56D9FCA1FFBFBA4B9B6547F7C0A4B705FEC0C"
FIXTURE = Path(__file__).parent / "fixtures" / "nfce" / "go" / f"{KEY}.html"
QR_URL = f"https://nfeweb.sefaz.go.gov.br/nfeweb/sites/nfce/danfeNFCe?p={KEY}|2|1|4|{SIG}"
DETAIL_URL = f"{DETAIL_PATH}?chNFe={KEY}"


@pytest.fixture
def detail() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _page(body: str, url: str = DETAIL_URL) -> FetchedPage:
    return FetchedPage(url=url, status_code=200, html=body, fetched_at=datetime.now(timezone.utc))


class TestFollowUp:
    def test_the_qr_page_asks_for_the_detailed_one(self):
        """The barcode is not on the page the QR leads to, so the note is
        read one request further in."""
        shell = _page('<button class="btn btn-view-det">Visualizar</button>', QR_URL)

        assert GoAdapter().follow_up(shell) == DETAIL_URL

    def test_the_detailed_page_does_not_ask_for_another(self, detail):
        """Following a detail view with a detail view would loop."""
        assert GoAdapter().follow_up(_page(detail)) is None

    def test_a_page_with_no_key_in_its_url_is_not_followed(self):
        shell = _page('<button class="btn btn-view-det">x</button>', "https://nfeweb.sefaz.go.gov.br/nfeweb/")

        assert GoAdapter().follow_up(shell) is None


class TestClassify:
    def test_an_authorised_note(self, detail):
        assert GoAdapter().classify(_page(detail)) == PageKind.AUTHORIZED

    def test_the_search_form_s_challenge_is_a_captcha(self):
        challenge = '<div class="cf-turnstile" data-sitekey="x"></div>'

        assert GoAdapter().classify(_page(challenge)) == PageKind.CAPTCHA


class TestParse:
    def test_the_note_reads_whole(self, detail):
        note = GoAdapter().parse(detail)

        assert note.access_key == KEY
        assert (note.series, note.number) == (2, 41902)
        assert note.model == "65"
        assert note.protocol == "152260854412095"
        assert note.issuer.cnpj == "20758851004607"
        assert note.issuer.legal_name == "EDN UTILIDADES DOMESTICAS IMP E EXP"
        assert note.issuer.trade_name == "BIGLAR CALDAS NOVAS 10"
        assert note.issuer.city == "CALDAS NOVAS" and note.issuer.uf == "GO"
        assert note.issued_at is not None and note.issued_at.day == 4

    def test_the_barcode_is_the_reason_this_page_is_read(self, detail):
        note = GoAdapter().parse(detail)

        assert [item.gtin for item in note.items] == ["07908216128651"]

    def test_the_item_keeps_its_numbers(self, detail):
        item = GoAdapter().parse(detail).items[0]

        assert item.product_code == "260391"
        assert item.description == "JOGO PANELAS ALUM PRATIC COOK 5PC CR - UN"
        assert (item.ncm, item.cfop, item.unit) == ("76151000", "5102", "UN")
        assert item.quantity == Decimal("1")
        assert item.unit_price == Decimal("349.99")
        assert item.total == Decimal("349.99")

    def test_the_totals_and_the_payment(self, detail):
        note = GoAdapter().parse(detail)

        assert note.totals.items_count == 1
        assert note.totals.products_total == Decimal("349.99")
        assert note.totals.total == Decimal("349.99")
        assert note.totals.approx_taxes == Decimal("137.37")
        assert [(p.type, p.amount) for p in note.payments] == [("credit_card", Decimal("349.99"))]

    def test_a_page_that_is_not_the_document_is_a_parse_error(self):
        with pytest.raises(ParseError):
            GoAdapter().parse("<html><body>Aguarde...</body></html>")


class TestUrl:
    def test_the_qr_url_is_preferred(self):
        assert GoAdapter().consulta_url(parse_qr_payload(QR_URL)) == QR_URL

    def test_the_signature_survives_a_rebuild(self):
        """Goiás checks it, so a key-only URL reaches the guarded form
        instead of the note — which is why `key_route_answers` is False."""
        rebuilt = GoAdapter().consulta_url(replace(parse_qr_payload(QR_URL), url=None))

        assert SIG in rebuilt
        assert GoAdapter().key_route_answers is False
