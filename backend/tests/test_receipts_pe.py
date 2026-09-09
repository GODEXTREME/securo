"""Pernambuco: the state that answers with the document itself.

The value of this adapter is not that it reads a page differently — it
is that the XML carries `cEAN`. Every other state leaves the catalogue
identifying items by the store's own product code, comparable only
within one chain; here the barcode arrives with the note.
"""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.receipts.adapters.base import FetchedPage, PageKind, ParseError
from app.receipts.adapters.pe import PeAdapter
from app.receipts.qr import parse_qr_payload

KEY = "26260906626253143858651010000802021783445888"
FIXTURE = Path(__file__).parent / "fixtures" / "nfce" / "pe" / f"{KEY}.xml"
URL = f"http://nfce.sefaz.pe.gov.br/nfce-web/consultarNFCe?p={KEY}|3|1"


@pytest.fixture
def xml() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _page(body: str) -> FetchedPage:
    return FetchedPage(url=URL, status_code=200, html=body, fetched_at=datetime.now(timezone.utc))


class TestClassify:
    def test_an_authorised_note_says_so_with_a_code(self, xml):
        assert PeAdapter().classify(_page(xml)) == PageKind.AUTHORIZED

    def test_a_cancelled_note_is_read_from_cStat(self, xml):
        assert PeAdapter().classify(_page(xml.replace("<cStat>100</cStat>", "<cStat>101</cStat>"))) == (
            PageKind.CANCELLED
        )

    def test_an_unknown_key_is_not_published_yet(self):
        envelope = (
            '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">'
            "<erro>Rejeicao</erro><consulta>1</consulta></nfeProc>"
        )
        assert PeAdapter().classify(_page(envelope)) == PageKind.NOT_FOUND_YET

    def test_something_that_is_not_xml_is_an_error_page(self):
        assert PeAdapter().classify(_page("<html><body>manutenção</body></html>")) == PageKind.ERROR_PAGE

    def test_a_status_with_no_rule_stops_rather_than_guesses(self, xml):
        """A fiscal state we have no rule for is not something to invent
        an answer about."""
        assert PeAdapter().classify(_page(xml.replace("<cStat>100</cStat>", "<cStat>301</cStat>"))) == (
            PageKind.ERROR_PAGE
        )


class TestParse:
    def test_the_note_reads_whole(self, xml):
        note = PeAdapter().parse(xml)

        assert note.access_key == KEY
        assert note.uf == "PE" and note.model == "65"
        assert (note.series, note.number) == (101, 80202)
        assert note.protocol == "226260816146794"
        assert note.issuer.cnpj == "06626253143858"
        assert note.issuer.legal_name == "Empreendimentos Pague Menos S.A."
        assert note.issuer.city == "CARPINA" and note.issuer.uf == "PE"
        assert note.issued_at is not None and note.issued_at.year == 2026
        assert note.source == "dfe_xml"

    def test_the_barcode_comes_with_the_note(self, xml):
        """The whole reason this state matters. `normalize_gtin` pads to
        GTIN-14, which is the catalogue's key."""
        note = PeAdapter().parse(xml)

        assert [item.gtin for item in note.items] == ["07891150094321", "07613034968364"]

    def test_items_keep_their_exact_numbers(self, xml):
        note = PeAdapter().parse(xml)
        first, second = note.items

        assert first.product_code == "76273"
        assert first.description == "PICOLE KIBON FRUTTAR"
        assert (first.ncm, first.cfop, first.unit) == ("21050010", "5405", "UN")
        assert first.quantity == Decimal("1.0000")
        assert first.unit_price == Decimal("7.9900000000")
        assert first.total == Decimal("7.99")
        assert second.description == "FORMULA INF NAN SUPR"
        assert second.total == Decimal("116.99")
        assert all(not isinstance(item.total, float) for item in note.items)

    def test_the_totals_are_the_document_s_own(self, xml):
        note = PeAdapter().parse(xml)

        assert note.totals.items_count == 2
        assert note.totals.products_total == Decimal("124.98")
        assert note.totals.total == Decimal("124.98")
        assert note.totals.discount == Decimal("0.00")
        assert note.totals.approx_taxes == Decimal("39.39")

    def test_both_payments_are_kept_with_their_codes(self, xml):
        note = PeAdapter().parse(xml)

        assert [(p.type, p.label, p.amount) for p in note.payments] == [
            ("store_credit", "05", Decimal("116.99")),
            ("debit_card", "04", Decimal("7.99")),
        ]

    def test_an_item_without_a_barcode_is_not_given_a_wrong_one(self, xml):
        """`SEM GTIN` is the portal saying there is none. A wrong key in
        the catalogue is worse than a missing one."""
        note = PeAdapter().parse(xml.replace("<cEAN>7891150094321</cEAN>", "<cEAN>SEM GTIN</cEAN>", 1))

        assert note.items[0].gtin is None
        assert note.items[1].gtin == "07613034968364"

    def test_a_document_without_items_is_a_parse_error(self, xml):
        stripped = xml
        for det in ("<det nItem=\"1\">", "<det nItem=\"2\">"):
            start = stripped.index(det)
            end = stripped.index("</det>", start) + len("</det>")
            stripped = stripped[:start] + stripped[end:]

        with pytest.raises(ParseError) as raised:
            PeAdapter().parse(stripped)
        assert raised.value.code == "no_items"


class TestUrl:
    def test_the_qr_url_is_preferred(self):
        assert PeAdapter().consulta_url(parse_qr_payload(URL)) == URL

    def test_the_key_alone_rebuilds_the_same_consultation(self):
        """Nothing is lost by dropping the URL: a three-field payload
        carries no signature, so the key reaches the same document."""
        payload = replace(parse_qr_payload(URL), url=None)

        assert PeAdapter().consulta_url(payload) == (
            f"http://nfce.sefaz.pe.gov.br/nfce-web/consultarNFCe?p={KEY}|3|1"
        )
