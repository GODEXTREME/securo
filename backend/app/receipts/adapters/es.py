"""Espírito Santo (cUF 32): `app.sefaz.es.gov.br/ConsultaNFCe`.

What the portal really does, observed 2026-09-06: the QR URL is answered
with 301 → 302 → `/ConsultaNFCe/QRCode.aspx?p=…`, and that page is a
**Cloudflare Turnstile challenge**, not the DANFE. An automated request
never sees the note. `classify` reports it as CAPTCHA, the receipt stops
retrying, and the user pastes the page their browser rendered after the
challenge (`POST /receipts/{id}/html`). That paste path is the primary
path for this state, not a fallback.

The page a browser renders after the challenge **is** the shared
tabResult template (fixture `32260800063960006050650050003784571128411294.html`,
captured 2026-09-06), with three quirks the parser now handles: the item
cell carries no class and names the product in a `span.txtTit`; the
totals block prints only "Valor a pagar", never the products total or a
discount line; and the payment line can come out as `NaN`.
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
    parser_version = 2
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
