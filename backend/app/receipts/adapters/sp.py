"""São Paulo (cUF 35): `www.nfce.fazenda.sp.gov.br/NFCeConsultaPublica`.

The cheapest state so far, and not the one that was expected. The design
notes had it down as guarded by a reCAPTCHA — recorded before anyone had
a real key to ask with, and wrong. Asked with the signature its QR
carries, the portal answers a plain request, with no challenge and no
browser, and what it answers is the shared ENCAT `tabResult` template
that Espírito Santo and Rio de Janeiro already use. So this adapter is a
binding and nothing more: no parser, no fixture format, no new failure
mode (checked 2026-09-13 against a real note).

Two things the probe settled that are not guesses:

The **signature is checked**. `?p=<key>|2|1` without it returns 200 and
the consultation form rather than the note, so there is no key route to
fall back on — the same position Goiás and Minas Gerais are in.

The **table's URL still works**. It names `/qrcode`, the portal answers
302 to `/NFCeConsultaPublica/Paginas/ConsultaQRCode.aspx`, and the note
arrives. It is nearly dead code either way: a QR brings its own URL, and
a typed key cannot be fetched here at all.

Like every consumer DANFE, the page carries the merchant's own product
code and no barcode, so a product from São Paulo is comparable within
its chain until somebody scans one.
"""
from __future__ import annotations

from typing import Optional

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.tabresult import classify_tabresult, parse_tabresult
from app.receipts.canonical import CanonicalReceipt
from app.receipts.qr import QrPayload
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for


class SpAdapter:
    c_uf = "35"
    uf = "SP"
    parser_version = 1
    allowed_hosts = allowed_hosts_for("SP")
    #: The portal checks the signature; without it the same URL answers
    #: with the search form instead of the note.
    key_route_answers = False

    def consulta_url(self, qr: QrPayload) -> str:
        if qr.url:
            return qr.url
        base = DEFAULT_CONSULTA_URLS["SP"]
        version = qr.version // 100 or 2
        if qr.has_signature:
            parts = [qr.key.key, str(version), str(qr.tp_amb), qr.c_id_token or "1", qr.signature or ""]
            return f"{base}?p={'|'.join(parts)}"
        return f"{base}?p={qr.key.key}|{version}|{qr.tp_amb}"

    def follow_up(self, page: FetchedPage) -> Optional[str]:
        """The consumer DANFE is all this portal offers a fetcher."""
        return None

    def classify(self, page: FetchedPage) -> PageKind:
        return classify_tabresult(page)

    def parse(self, html: str) -> CanonicalReceipt:
        return parse_tabresult(html, expected_uf=self.uf)
