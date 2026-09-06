"""Consumer receipts (NFC-e): reading the QR code, fetching the note from the
issuing state's portal, and turning it into a canonical document.

Layering, strictest first:

  - `qr`, `gtin`, `canonical`, `normalize` know nothing about HTTP or the
    database. They are pure and are tested with strings.
  - `adapters/*` turn one state's HTML into the canonical model. They know
    nothing about HTTP or the database either: an adapter is tested with
    a saved `.html` and nothing else.
  - `fetcher` is the only module that talks to a portal. Host allowlist,
    rate limit, circuit breaker and timeouts all live there.
  - `services/receipt_service` is the only layer that touches the database
    and the one that owns the state machine.

Deliberately not under `app/fiscal/`: that package is upstream's and is
about *identification* documents (CNPJ, VAT). This is about *fiscal
documents*, and mixing the two would make every upstream sync a conflict.
"""
