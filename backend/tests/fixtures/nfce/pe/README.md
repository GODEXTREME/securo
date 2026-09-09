# Fixtures — Pernambuco (cUF 26)

`26260906626253143858651010000802021783445888.xml` — **real**, captured
2026-09-09 from `nfce.sefaz.pe.gov.br`.

Pernambuco does not render a DANFE for the QR consultation: it answers
with the authorised document, a `procNFe` 4.00 wrapped in the state's
own envelope (`<nfeProc><proc>…</proc><protNFe>…</protNFe>null</nfeProc>`
— the trailing `null` is the portal's, and is kept because the parser
has to tolerate it).

It is kept because it is the only fixture where the barcode is present.
`det/prod/cEAN` carries a real GTIN on both items, which is what lets the
catalogue identify them globally instead of per chain.

## What was masked, and what was not

The buyer's name, e-mail and address (`dest`), and the technical
contact's name, e-mail and phone (`infRespTec`), were replaced. So were
the signature, digest and certificate blobs — they are large, they name
a person in the certificate subject, and nothing here reads them.

Everything fiscal is untouched: issuer, items, quantities, prices,
totals, payments and the authorisation protocol are exactly as the state
served them, because those are what the tests assert.
