"""Espírito Santo (cUF 32): `app.sefaz.es.gov.br/ConsultaNFCe/`.

What the portal really does, observed 2026-09-06: the QR URL is answered
with 301 → 302 → `/ConsultaNFCe/QRCode.aspx?p=…`, and that page is a
**Cloudflare Turnstile challenge**, not the DANFE. An automated request
never sees the note. `classify` reports it as CAPTCHA, the receipt stops
retrying, and the user pastes the page their browser rendered after the
challenge (`POST /receipts/{id}/html`). That paste path is the primary
path for this state, not a fallback.

**No deep link opens here** (2026-09-13). Not `?chNFe=`, which was
already known to land on an empty form, and not the `?p=…` link the QR
itself carries: following it does not end on the note. The one route
that works is the consultation form — open `/ConsultaNFCe/`, pass the
check, put the key in, press Consultar — so that is the only URL this
adapter ever names, for the browser and for the person alike. Sending
either to a link that does not open is worse than sending them to a
form that does, because a form can be filled and a dead link cannot.

The cost is that the URL no longer identifies the note: every receipt
in this state names the same page, and the key it is asked with lives
on the screen rather than in the address. What follows from that is in
`consulta_url` below and in the tab bookkeeping in `browser.py`.

The page a browser renders after the challenge **is** the shared
tabResult template (fixture `32260800063960006050650050003784571128411294.html`,
captured 2026-09-06), with three quirks the parser now handles: the item
cell carries no class and names the product in a `span.txtTit`; the
totals block prints only "Valor a pagar", never the products total or a
discount line; and the payment line can come out as `NaN`.
"""
from __future__ import annotations

from typing import Optional

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.tabresult import classify_tabresult, parse_tabresult
from app.receipts.canonical import CanonicalReceipt
from app.receipts.qr import QrPayload
from app.receipts.uf_table import allowed_hosts_for


#: The consultation form, and the whole of this state's route in. Kept
#: here rather than in the URL table because it is not the QR endpoint
#: the table holds for every other state — it is the page a person fills
#: in, which is a different thing that happens to live next door.
CONSULTA_FORM = "http://app.sefaz.es.gov.br/ConsultaNFCe/"


class EsAdapter:
    c_uf = "32"
    uf = "ES"
    parser_version = 2
    allowed_hosts = allowed_hosts_for("ES")
    #: No URL answers with the note here — see the module docstring — so
    #: there is nothing to fall back to when the QR is refused, and no
    #: request worth spending on a key alone.
    key_route_answers = False

    def consulta_url(self, qr: QrPayload) -> str:
        """The form, whatever the QR carried.

        The signature is discarded along with the rest of the deep link.
        That is a real loss — it is the part the portal checks, and it
        cannot be typed — but a link that does not open carries it
        nowhere. The key is what the form asks for, and the key is on
        the receipt.
        """
        return CONSULTA_FORM

    def follow_up(self, page: FetchedPage) -> Optional[str]:
        """The consumer DANFE is all this portal offers a fetcher."""
        return None

    def classify(self, page: FetchedPage) -> PageKind:
        return classify_tabresult(page)

    def parse(self, html: str) -> CanonicalReceipt:
        return parse_tabresult(html, expected_uf=self.uf)
