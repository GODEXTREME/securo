"""Espírito Santo (cUF 32): `app.sefaz.es.gov.br/ConsultaNFCe`.

A binding over the shared tabResult template. The URL that came inside the
QR is always preferred: it carries the signature the portal checks. When
only the bare key is known, the fallback URL asks by `chNFe=`; the portal
is expected to answer that with a challenge, which `classify` reports as
CAPTCHA so the user can paste the page instead.

`parser_version` starts at 1 and is bumped with every change to what
`parse` produces. Fixture: `tests/fixtures/nfce/es/`.
"""
from __future__ import annotations

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.tabresult import classify_tabresult, parse_tabresult
from app.receipts.canonical import CanonicalReceipt
from app.receipts.qr import QrPayload
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for


class EsAdapter:
    c_uf = "32"
    uf = "ES"
    parser_version = 1
    allowed_hosts = allowed_hosts_for("ES")

    def consulta_url(self, qr: QrPayload) -> str:
        if qr.url:
            return qr.url
        base = DEFAULT_CONSULTA_URLS["ES"]
        if qr.has_signature:
            p = "|".join([qr.key.key, str(qr.version // 100), str(qr.tp_amb), qr.c_id_token or "1", qr.signature or ""])
            return f"{base}?p={p}"
        return f"{base}?chNFe={qr.key.key}"

    def classify(self, page: FetchedPage) -> PageKind:
        return classify_tabresult(page)

    def parse(self, html: str) -> CanonicalReceipt:
        return parse_tabresult(html, expected_uf=self.uf)
