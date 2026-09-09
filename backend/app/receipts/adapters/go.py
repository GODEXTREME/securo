"""Goiás (cUF 52): `nfeweb.sefaz.go.gov.br/nfeweb/sites/nfce`.

What the portal really does, observed 2026-09-09: the search form is
behind a Cloudflare challenge, but **the QR route is not**. A plain
request to `danfeNFCe?p=…` is answered, and the note itself is rendered
into an iframe by JavaScript.

That page is not the one worth reading. Its "Visualizar NFC-e detalhada"
button leads to the national detailed view, and *that* one carries
`Código EAN Comercial` — the barcode the consumer DANFE never shows. So
this adapter reads the detail view instead, reached with `follow_up`.

The detail view refuses a cold request with the same challenge the form
gets. What admits it is the session the QR consultation just
established, which is why the second request has to travel on the first
one's client rather than being fetched on its own.
"""
from __future__ import annotations

from typing import Optional

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.nfe_detail import classify_nfe_detail, parse_nfe_detail
from app.receipts.canonical import CanonicalReceipt
from app.receipts.qr import QrPayload
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for

DETAIL_PATH = "https://nfeweb.sefaz.go.gov.br/nfeweb/sites/nfce/render/NFCe"


class GoAdapter:
    c_uf = "52"
    uf = "GO"
    parser_version = 1
    allowed_hosts = allowed_hosts_for("GO")
    #: The QR carries a signature and the consultation checks it; the key
    #: alone reaches the challenge-guarded form instead.
    key_route_answers = False

    def consulta_url(self, qr: QrPayload) -> str:
        if qr.url:
            return qr.url
        base = DEFAULT_CONSULTA_URLS["GO"]
        version = qr.version // 100 or 2
        if qr.has_signature:
            parts = [qr.key.key, str(version), str(qr.tp_amb), qr.c_id_token or "1", qr.signature or ""]
            return f"{base}?p={'|'.join(parts)}"
        return f"{base}?p={qr.key.key}|{version}|{qr.tp_amb}"

    def follow_up(self, page: FetchedPage) -> Optional[str]:
        """The detailed view for the note just served.

        Only asked for when the page is the one that opens the session —
        following a detail view with another detail view would loop.
        """
        if "btn-view-det" not in page.html:
            return None
        key = _key_of(page.url)
        return f"{DETAIL_PATH}?chNFe={key}" if key else None

    def classify(self, page: FetchedPage) -> PageKind:
        return classify_nfe_detail(page)

    def parse(self, html: str) -> CanonicalReceipt:
        return parse_nfe_detail(html)


def _key_of(url: str) -> Optional[str]:
    import re

    found = re.search(r"\d{44}", url)
    return found.group(0) if found else None
