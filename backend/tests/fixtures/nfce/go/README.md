# Fixtures — Goiás (cUF 52)

`52260920758851004607650020000419021267999864.html` — **real**, captured
2026-09-09 from `nfeweb.sefaz.go.gov.br`.

This is the *detailed* view (`render/NFCe`), not the DANFE the QR leads
to, and it is kept because of one field the consumer template never
shows: `Código EAN Comercial`. The note's single item carries a real
GTIN, which is what lets the catalogue identify it across chains.

The page is reached in two requests — the QR consultation first, then
this one on the same client. Asked for on its own it answers with a
Cloudflare challenge; the session the first request opens is what admits
it.

## What was trimmed

Analytics and framework scripts, which the parser never reads, and the
empty container the page fills in the browser. The `new XmlNFE(…)`
payload — the escaped markup that holds the whole document — is exactly
as served.

Nothing was masked: the note names a business as issuer and has no
consumer on it (`Destinatário` is empty, as it is on most NFC-e).
