"""Minas Gerais (cUF 31).

No adapter yet: both of the state's routes are answered with a Cloudflare
Turnstile — the QR consultation (`qrcode.xhtml?p=…`) and the search by
key (`consultaarg.xhtml`) alike, checked 2026-09-10 — so reading a note
there will need the browser, as it does in Espírito Santo. What is
settled and testable now is where the state answers at all.
"""
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for, current_portal_url


class TestTheHostThatAnswers:
    OLD = (
        "https://nfce.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml"
        "?p=31260913482024000257650010001805631869078341|2|1|1|54CA4F008CFF4E67B7EB33418830851449FB5392"
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
