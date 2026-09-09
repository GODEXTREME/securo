"""Pernambuco (cUF 26): `nfce.sefaz.pe.gov.br/nfce-web/consultarNFCe`.

What the portal really does, observed 2026-09-09: the QR URL is answered
with the **authorised XML** — a `procNFe` 4.00 inside the state's own
consultation envelope — and not with a rendered DANFE. A plain request
gets it: no challenge, no browser, no User-Agent games.

That makes Pernambuco the first state where the catalogue gets what it
was designed around. `det/prod/cEAN` carries the barcode, so items are
globally identifiable the moment they are read, and a price paid here
compares against the same product bought anywhere. Everywhere else that
only happens after a person scans the barcode by hand, because the
shared HTML template does not print it.

The QR is the three-field form (`chave|versão|tpAmb`); there is no
signature to preserve, so the key alone reaches the same document.
"""
from __future__ import annotations

from typing import Optional

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.nfe_xml import classify_nfe_xml, parse_nfe_xml
from app.receipts.canonical import CanonicalReceipt
from app.receipts.qr import QrPayload
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for


class PeAdapter:
    c_uf = "26"
    uf = "PE"
    parser_version = 1
    allowed_hosts = allowed_hosts_for("PE")
    #: The same URL with the key alone answers with the same document —
    #: there is no signature in a three-field payload to lose.
    key_route_answers = True

    def consulta_url(self, qr: QrPayload) -> str:
        if qr.url:
            return qr.url
        base = DEFAULT_CONSULTA_URLS["PE"]
        return f"{base}?p={qr.key.key}|{qr.version // 100}|{qr.tp_amb}"

    def follow_up(self, page: FetchedPage) -> Optional[str]:
        """The XML is the whole document already."""
        return None

    def classify(self, page: FetchedPage) -> PageKind:
        return classify_nfe_xml(page)

    def parse(self, html: str) -> CanonicalReceipt:
        return parse_nfe_xml(html)
