"""Minas Gerais (cUF 31): `portalsped.fazenda.mg.gov.br/portalnfce`.

What the portal really does, observed 2026-09-10 and 2026-09-11: both
routes ask for a person. The QR consultation (`qrcode.xhtml?p=…`) answers
200 with a Cloudflare Turnstile and a "Visualizar" button that is a JSF
postback; the search by key (`consultaarg.xhtml`) is guarded the same
way. Neither shows a fetcher anything, so this state goes through the
browser, as Espírito Santo does.

One difference from Espírito Santo worth knowing when watching it work:
passing the challenge is not enough. The person still has to press
"Visualizar", and only then does the portal POST its way to
`infoqrcode.xhtml`, which is the page the parser reads.
"""
from __future__ import annotations

from typing import Optional

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.mg_info import classify_mg_info, parse_mg_info
from app.receipts.canonical import CanonicalReceipt
from app.receipts.qr import QrPayload
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for


class MgAdapter:
    c_uf = "31"
    uf = "MG"
    parser_version = 1
    allowed_hosts = allowed_hosts_for("MG")
    #: `consultaarg.xhtml` is a form behind the same challenge, so asking
    #: for it with a key alone teaches a fetcher nothing.
    key_route_answers = False

    def consulta_url(self, qr: QrPayload) -> str:
        if qr.url:
            return qr.url
        base = DEFAULT_CONSULTA_URLS["MG"]
        version = qr.version // 100 or 2
        if qr.has_signature:
            parts = [qr.key.key, str(version), str(qr.tp_amb), qr.c_id_token or "1", qr.signature or ""]
            return f"{base}?p={'|'.join(parts)}"
        return f"{base}?p={qr.key.key}|{version}|{qr.tp_amb}"

    def follow_up(self, page: FetchedPage) -> Optional[str]:
        """Nothing further: `infoqrcode.xhtml` is everything this portal
        shows, and it is reached by a form post rather than a URL."""
        return None

    def classify(self, page: FetchedPage) -> PageKind:
        return classify_mg_info(page)

    def parse(self, html: str) -> CanonicalReceipt:
        return parse_mg_info(html)
