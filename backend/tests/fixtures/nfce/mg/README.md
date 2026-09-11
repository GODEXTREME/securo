# Fixtures — Minas Gerais (cUF 31)

`31260913482024000257650010001805631869078341.html` — **real**, captured
2026-09-11 from `portalsped.fazenda.mg.gov.br`.

This is `infoqrcode.xhtml`, the page the portal renders after a person
passes the Cloudflare Turnstile on the QR consultation and presses
"Visualizar". A fetcher never sees it; it arrives through the browser.

Kept because it is a layout nothing else in this repository shares: the
state's own JSF page, with the fiscal detail folded into an accordion,
rather than the ENCAT DANFE (Espírito Santo, Rio de Janeiro), the
national detailed XSLT (Goiás) or the raw `procNFe` (Pernambuco).

Two things the tests read it for in particular:

- **It has no barcode.** The item names the merchant's own code
  ("Código: 2165"), which is why a product from this state stays
  comparable within its chain until somebody scans one.
- **It prints money two ways.** The item table says `R$ 6,00` and the
  summary rows say `6.00`, which is Java's `toString()` rather than a
  Brazilian number. The tests rewrite both to a value where the two
  readings disagree, because on this particular note they happen to
  agree and a fixture that cannot fail proves nothing.

## What was trimmed

Stylesheet and script tags, the navigation bar, the print button's
handler and the framework's inline configuration — none of which the
parser reads. The `javax.faces.ViewState` value was replaced with zeros
and the `jsessionid` path parameters dropped: both are session tokens,
expired but pointless to keep.

## What was masked

One word. The complementary information block carries the shop's
operator line, `Operador: 2 Vendedor: 1908-…`, which names an employee;
the name is replaced with `NOME`. The approximate-tax figures in that
same string are untouched, because a test reads them.

Nothing else is masked: the issuer is a business, and this note has no
consumer on it — the portal's consumer panel has room for a name and a
state, never a CPF, and here both are empty.
