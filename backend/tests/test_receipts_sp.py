"""São Paulo (cUF 35).

The state that turned out to cost nothing: it serves the shared ENCAT
template to a plain request, so what is worth testing is the binding —
that the right parser is reached, that the signature is known to be
required, and that the note this fixture holds comes out whole.
"""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.registry import adapter_for
from app.receipts.adapters.sp import SpAdapter
from app.receipts.qr import parse_qr_payload
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for

FIXTURES = Path(__file__).parent / "fixtures" / "nfce" / "sp"
KEY = "35260907128576000420650100001042781002063709"
SIG = "f1d191403f106c06edee7febbc857a5295310f50"
QR = (
    "https://www.nfce.fazenda.sp.gov.br/NFCeConsultaPublica/Paginas/ConsultaQRCode.aspx"
    f"?p={KEY}|2|1|1|{SIG}"
)


@pytest.fixture
def note() -> str:
    return (FIXTURES / f"{KEY}.html").read_text(encoding="utf-8")


def page(html: str, status: int = 200) -> FetchedPage:
    return FetchedPage(url=QR, status_code=status, html=html, fetched_at=datetime.now())


class TestTheBinding:
    def test_the_state_is_registered(self):
        adapter = adapter_for("35")
        assert adapter is not None and adapter.uf == "SP"

    def test_the_host_is_allowed(self):
        assert "www.nfce.fazenda.sp.gov.br" in allowed_hosts_for("SP")

    def test_the_qr_url_is_preferred_over_the_table(self):
        assert SpAdapter().consulta_url(parse_qr_payload(QR)) == QR

    def test_the_signature_survives_a_rebuild(self):
        """The portal checks it: the same URL without it answers with the
        search form instead of the note, which is why there is no key
        route to fall back on."""
        rebuilt = SpAdapter().consulta_url(replace(parse_qr_payload(QR), url=None))

        assert rebuilt.startswith(f"{DEFAULT_CONSULTA_URLS['SP']}?p={KEY}|2|1|1|")
        assert rebuilt.endswith(SIG)
        assert SpAdapter().key_route_answers is False

    def test_nothing_further_to_fetch(self):
        assert SpAdapter().follow_up(page("<html/>")) is None


class TestReadingTheNote:
    def test_the_page_is_recognised(self, note):
        assert SpAdapter().classify(page(note)) is PageKind.AUTHORIZED

    def test_the_header_facts(self, note):
        r = SpAdapter().parse(note)
        assert r.access_key == KEY
        assert r.uf == "SP"
        assert r.series == 10 and r.number == 104278
        assert r.protocol == "135266262517608"

    def test_the_issuer(self, note):
        issuer = SpAdapter().parse(note).issuer
        assert issuer.cnpj == "07128576000420"
        assert issuer.legal_name == "SUPERMERCADO TRIALBA LTDA."
        assert issuer.uf == "SP"

    def test_the_items_and_the_arithmetic(self, note):
        """The canonical model refuses a receipt whose lines do not add up
        to its header, so a parse that returns at all has already checked
        this — these assertions name the numbers it checked."""
        r = SpAdapter().parse(note)
        assert len(r.items) == 10 and r.totals.items_count == 10
        assert r.totals.products_total == Decimal("98.89")
        assert r.totals.discount == Decimal("1.00")
        assert r.totals.total == Decimal("97.89")
        assert sum(i.total for i in r.items) == r.totals.products_total

    def test_a_weighed_line_keeps_its_unit(self, note):
        """`0,258 KG` at R$ 54,89/kg — the case where quantity is not a
        count and the unit price is not the line total."""
        weighed = [i for i in SpAdapter().parse(note).items if i.unit == "KG"]
        assert weighed, "the fixture was chosen for having one"
        assert weighed[0].quantity == Decimal("0.258")
        assert weighed[0].unit_price == Decimal("54.89")

    def test_the_payment(self, note):
        payments = SpAdapter().parse(note).payments
        assert len(payments) == 1
        assert payments[0].type == "credit_card"
        assert payments[0].amount == Decimal("97.89")

    def test_the_consumer_danfe_carries_no_barcode(self, note):
        """As everywhere else this template is served: the merchant's own
        code and nothing global, so a product stays comparable within its
        chain until somebody scans one."""
        assert all(item.gtin is None for item in SpAdapter().parse(note).items)
        assert all(item.product_code for item in SpAdapter().parse(note).items)

    def test_this_note_names_no_consumer(self, note):
        assert SpAdapter().parse(note).customer_cpf is None
