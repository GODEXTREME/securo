"""Rio de Janeiro (cUF 33): `consultadfe.fazenda.rj.gov.br/consultaNFCe`.

What the portal really does, observed 2026-09-07: it answers a request
whose User-Agent looks like a browser, and serves anything else a block
page written as an IP-reputation notice. What comes back is an **F5
Shape** interstitial (`/TSPD/`) that computes a cookie in JavaScript;
a plain fetch stops there and headless Chromium had its navigation
aborted. So, as in Espírito Santo, the page reaches us through the
person's own browser — by capture or by paste — and the fetcher is kept
correct for the day the portal answers it.

The DANFE is the same shared tabResult template ES serves, and the
parser read a real note unchanged on the first attempt.

Two things this state does that ES does not:

  * Its QR carries three fields — `chave|versão|ambiente`, no token and
    no hash — which `consulta_url` rebuilds when only the key is known.
  * Its own validator calls that QR malformed ("A versão do QR Code deve
    ser 2", "O Código do Hash do QR Code deve ter 40 caracteres") and
    prints the note anyway. Refusing the payload would mean refusing
    receipts Rio de Janeiro itself issues and answers.
"""
from __future__ import annotations

from app.receipts.adapters.base import FetchedPage, PageKind
from app.receipts.adapters.tabresult import classify_tabresult, parse_tabresult
from app.receipts.canonical import CanonicalReceipt
from app.receipts.qr import QrPayload
from app.receipts.uf_table import DEFAULT_CONSULTA_URLS, allowed_hosts_for

#: What the state emits. Used when a key was typed rather than scanned,
#: so the URL we build looks like the one the QR would have carried.
DEFAULT_QR_VERSION = 3


class RjAdapter:
    c_uf = "33"
    uf = "RJ"
    parser_version = 1
    allowed_hosts = allowed_hosts_for("RJ")

    def consulta_url(self, qr: QrPayload) -> str:
        if qr.url:
            return qr.url
        base = DEFAULT_CONSULTA_URLS["RJ"]
        version = qr.version // 100 or DEFAULT_QR_VERSION
        return f"{base}?p={qr.key.key}|{version}|{qr.tp_amb}"

    def classify(self, page: FetchedPage) -> PageKind:
        return classify_tabresult(page)

    def parse(self, html: str) -> CanonicalReceipt:
        return parse_tabresult(html, expected_uf=self.uf)
