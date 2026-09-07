"""Rio de Janeiro against the page the portal really serves.

The state shares Espírito Santo's tabResult template, so most of what is
asserted here is that sharing it was true — and the parts that differ,
which are the reason this fixture is kept.
"""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.registry import ADAPTERS, adapter_for, supported_ufs
from app.receipts.adapters.rj import RjAdapter
from app.receipts.qr import parse_access_key, parse_qr_payload
from app.receipts.uf_table import current_portal_url

FIXTURE = Path(__file__).parent / "fixtures" / "nfce" / "rj"
KEY = "33260942591651053859650220000294281073101411"
REAL = FIXTURE / f"{KEY}.html"


def _page(html: str, status: int = 200) -> FetchedPage:
    return FetchedPage(
        url="https://consultadfe.fazenda.rj.gov.br/consultaNFCe/QRCode",
        status_code=status, html=html, fetched_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def html() -> str:
    return REAL.read_text(encoding="utf-8")


class TestRegistration:
    def test_the_state_is_supported(self):
        assert adapter_for("33") is not None
        assert "RJ" in supported_ufs()
        assert ADAPTERS["33"].uf == "RJ"

    def test_the_portal_it_moved_to_is_allowed(self):
        """The QR points at consultadfe; the old host stays allowed
        because paper outlives a migration."""
        hosts = RjAdapter.allowed_hosts
        assert "consultadfe.fazenda.rj.gov.br" in hosts
        assert "www4.fazenda.rj.gov.br" in hosts


class TestConsultaUrl:
    def test_prefers_the_url_the_qr_carried(self):
        payload = parse_qr_payload(
            f"https://consultadfe.fazenda.rj.gov.br/consultaNFCe/QRCode?p={KEY}|3|1"
        )
        assert RjAdapter().consulta_url(payload) == payload.url

    def test_rebuilds_the_three_field_form_from_a_typed_key(self):
        payload = parse_qr_payload(KEY)
        url = RjAdapter().consulta_url(payload)
        # The shape the state emits, not the five-field one ES uses.
        assert url.endswith(f"?p={KEY}|3|1")


class TestRealPage:
    def test_classifies_as_authorized(self, html):
        assert RjAdapter().classify(_page(html)) == PageKind.AUTHORIZED

    def test_reads_the_whole_note(self, html):
        r = RjAdapter().parse(html)
        assert r.access_key == KEY and r.uf == "RJ"
        assert r.number == 29428 and r.series == 22
        assert r.protocol == "233262097876317"
        assert r.issuer.legal_name == "ARCOS DOURADOS COMERCIO DE ALIMENTOS SA"
        assert r.issuer.cnpj == "42591651053859"
        assert (r.issuer.city, r.issuer.uf) == ("MACAE", "RJ")
        assert r.issuer.street == "AV. CARLOS AUGUSTO TINOCO GARCIA"
        assert r.issuer.number == "S/N"
        assert r.issuer.district == "VISCONDE DE ARAUJO"
        assert r.totals.items_count == 3
        assert r.totals.total == Decimal("29.90")
        assert [item.total for item in r.items] == [Decimal("7.50"), Decimal("16.90"), Decimal("5.50")]
        assert [item.product_code for item in r.items] == ["85790", "97884", "67814"]

    def test_reads_what_the_es_note_does_not_have(self, html):
        """The reason this fixture is kept: an offset on the emission
        time, "às" in the protocol line, a named payment with change, and
        the approximate-taxes line."""
        r = RjAdapter().parse(html)
        assert r.issued_at is not None and r.issued_at.utcoffset() is not None
        assert r.authorized_at is not None
        assert r.issued_at.hour == 18 and r.issued_at.minute == 40
        assert r.totals.approx_taxes == Decimal("1.71")
        assert len(r.payments) == 1
        payment = r.payments[0]
        assert payment.type == "credit_card"
        assert payment.amount == Decimal("29.90") and payment.change == Decimal("0.00")

    def test_the_consumer_cpf_is_read_for_hashing_not_kept(self, html):
        """The fixture's CPF is masked; what matters is that the parser
        finds one, since the service stores only its salted hash."""
        r = RjAdapter().parse(html)
        assert r.customer_cpf == "00000000000"


class TestTheOldHost:
    """Older receipts point at `www4`, which now answers a refusal. The
    query on them is still right — only the host is stale."""

    OLD = (
        "http://www4.fazenda.rj.gov.br/consultaNFCe/QRCode"
        "?p=33260932360034000183650010008486231036678129|2|1|1|34A4A6EFC5FC538989F868EAF19E19DB856700C8"
    )

    def test_the_query_moves_to_the_portal_that_answers(self):
        moved = current_portal_url(self.OLD, "RJ")
        assert moved is not None
        assert moved.startswith("https://consultadfe.fazenda.rj.gov.br/consultaNFCe/QRCode?p=")
        # The signature is what the portal checks; losing it would turn a
        # readable note into "QR Code Inválido".
        assert moved.endswith("|2|1|1|34A4A6EFC5FC538989F868EAF19E19DB856700C8")

    def test_a_url_already_on_the_current_host_is_left_alone(self):
        assert current_portal_url("https://consultadfe.fazenda.rj.gov.br/consultaNFCe/QRCode?p=x", "RJ") is None

    def test_a_state_with_no_old_host_is_left_alone(self):
        assert current_portal_url("http://app.sefaz.es.gov.br/ConsultaNFCe?p=x", "ES") is None

    def test_the_refusal_page_is_named_as_such(self):
        """It reads as an IP-reputation notice; what it means is "not
        you". Left as a generic error it would earn eight retries."""
        page = (
            "<body>SECRETARIA DE ESTADO DE FAZENDA DO RIO DE JANEIRO<br/>"
            " nosso serviço de segurança da informação bloqueia acessos"
            " provenientes desses endereços IP</body>"
        )
        assert RjAdapter().classify(_page(page)) == PageKind.NEEDS_BROWSER


class TestConsultaUrlKeepsTheSignature:
    def test_a_five_field_qr_is_rebuilt_as_five(self):
        payload = parse_qr_payload(
            "http://www4.fazenda.rj.gov.br/consultaNFCe/QRCode"
            "?p=33260932360034000183650010008486231036678129|2|1|1|34A4A6EFC5FC538989F868EAF19E19DB856700C8"
        )
        url = RjAdapter().consulta_url(replace(payload, url=None))
        assert url.endswith("|2|1|1|34A4A6EFC5FC538989F868EAF19E19DB856700C8")


class TestWhatThePortalAnswersAMachine:
    """The two pages a fetcher actually gets, and why neither is worth
    retrying eight times."""

    def test_the_f5_interstitial_is_named_as_such(self):
        wall = (
            '<html><head><script src="/TSPD/?type=18"></script>'
            "<APM_DO_NOT_TOUCH></APM_DO_NOT_TOUCH></head><body></body></html>"
        )
        assert RjAdapter().classify(_page(wall)) == PageKind.NEEDS_BROWSER

    def test_the_real_note_is_not_mistaken_for_it(self, html):
        """The DANFE carries the same scripts. Reading the page before
        the wall is the whole point of the check order."""
        assert "/TSPD/" in html and "APM_DO_NOT_TOUCH" in html
        assert RjAdapter().classify(_page(html)) == PageKind.AUTHORIZED


class TestQrPayload:
    def test_the_three_field_payload_is_this_state(self):
        payload = parse_qr_payload(
            f"https://consultadfe.fazenda.rj.gov.br/consultaNFCe/QRCode?p={KEY}|3|1"
        )
        assert payload.key.uf == "RJ" and payload.version == 300
        assert not payload.has_signature
        assert parse_access_key(KEY).is_nfce
