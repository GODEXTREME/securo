# RFC — Consumer receipts (NFC-e): reading a note, and what a price history costs

Status: shipping in parts · PRs #38–#47

## Problem

A grocery line in a transaction says `SUPERMERCADO X — R$ 145,93`. What was
bought, at what unit price, and whether that price is better or worse than
last month, is on the receipt — and the receipt is a QR code the till
prints. Brazil publishes every one of them: the NFC-e access key on the
paper is enough for the consumer to consult the note at their state's
portal.

So the data is public and identified. The work is in three parts, and
only the first is obvious:

1. Read the note (parse the QR, fetch the page, parse the DANFE).
2. Turn a printed line into a **product**, stably enough that two
   receipts months apart agree it is the same thing.
3. Answer the question a person actually has: *is this cheaper than
   last time?*

## Reading a note

### The QR

`parse_qr_payload` accepts what a scanner or a person can produce: the
QR's URL, a bare 44-digit key, or text containing either. Three payload
shapes exist in the wild and all three are in use by states we support:

| fields | shape | seen in |
|---|---|---|
| 3 | `chave\|versão\|tpAmb` | RJ |
| 5 | `chave\|versão\|tpAmb\|cIdToken\|cHashQRCode` | ES |
| 9 | the five plus `dhEmi, vNF, vICMS, digVal` | offline contingency |

The access key carries a mod-11 check digit and the CNPJ its own two, so
a mistyped or misread key is caught before anything is fetched. The
signature at the end of the URL carries **no** check digit — the one
part of a QR that can be wrong while everything else validates. A
misread there produces a link the portal refuses ("QR Code Inválido")
for a note that is perfectly real, which is why a refusal is its own
state (`qr_rejected`) rather than an error to retry eight times, and why
rescanning replaces the stored URL.

**Policy is separate from parsing.** A homologation note and an NF-e are
both well-formed; they are simply not consumer receipts. They are stored
as `invalid` with the reason, so the list says why rather than swallowing
them.

### Fetching, and why it mostly does not work

The fetcher is deliberately narrow, because the URL is user input: an
exact host allowlist per state, refusal to follow a redirect out of it,
refusal to resolve to a private address, one rate token per fetch, a
circuit breaker per state, a 15-second timeout.

None of that is what stops it. The portals do:

| | Espírito Santo | Rio de Janeiro |
|---|---|---|
| defence | Cloudflare Turnstile | F5 Shape (`/TSPD/`) |
| plain request | interactive challenge | blocked on User-Agent |
| browser User-Agent | still the challenge | reaches an interstitial that runs JS |
| headless Chromium | not tried (a human must click) | navigation aborted |
| the person's own browser | works | works |

Two different walls, one shape: **neither answers a server, both answer
the person.** That is the finding the whole feature is built around, and
it was expensive to establish — a "403" from a corporate proxy looks
exactly like a portal refusing you, and an IP-reputation block page turns
out to be a User-Agent filter.

We do not defeat either defence. A challenge is a request for a human,
and FlareSolverr-style solvers both fail against Turnstile today and
answer a question nobody asked us to answer.

### So the browser brings the page

`POST /api/receipt-capture` takes a page from a bookmarklet running on
the portal's own origin, after the person has passed whatever was asked.
Two things make that work:

- **A credential that survives leaving our origin.** No cookie of ours
  reaches a page served by the state, so a capture token does: scoped to
  one workspace, stored as a sha256 hash, shown once, revocable. Minting
  it goes through the write gate; the route then trusts the token.
- **A note that identifies itself.** The bookmarklet knows nothing about
  which receipt it is looking at, so `find_access_key` reads the key off
  the page — validating the check digit and the state, so a run of
  digits that is neither is not mistaken for one. A key nobody has
  scanned becomes a receipt on the spot.

The body is `text/plain` so the browser sends it without a preflight the
portal's page would have to survive, and `Access-Control-Allow-Origin` is
echoed only for origins the adapters already recognise as portals.

Pasting the page by hand still works and still has its uses; it is the
same parser either way.

## Turning a line into a product

A till prints `ARROZ TIO JOAO T1 5KG`. Two receipts, two stores, two
spellings. Identity has three levels, and **only the first is
trustworthy**:

- **GTIN** — a barcode. Globally comparable. A product with one is
  `global`.
- **Chain code** (`cnpj_root:product_code`) — the store's own SKU.
  Comparable within that chain and nowhere else.
- **Text fingerprint** — abbreviations expanded from a versioned table,
  size parsed out (`450G`, `1,5L`, `6X350ML`, `C/12`). Good enough to
  *suggest*, never to merge.

The one automatic merge is a GTIN arriving beside a chain code that
already names a chain-scoped product: the barcode proves what the text
only hinted. Everything else is a suggestion (Jaro-Winkler ≥ 0.92 and the
same size) for a person to accept. Merged products stay as tombstones so
old links keep resolving.

**Scope is derived, not stored**: a product is `global` exactly when it
has a GTIN. That is why the barcode scanner matters beyond convenience —
scanning a product and pointing at an old unlabelled line is the only
way a chain-scoped product becomes globally comparable, and no amount of
string matching can do it safely.

## Answering the question

Price points are append-only, one per receipt line, upserted by line so
reprocessing never doubles. Prices are normalised to R$/kg, R$/l or
R$/un, because comparing a 1 kg pack with a 400 g one on the line total
is not a comparison. Where a line cannot be reduced to a base unit, the
UI says so rather than implying a comparison that was never made.

Outliers (>10× or <0.1× the product's yearly median, with at least two
other points) stay in the history and out of the answers — struck
through, not hidden: a price that looks wrong is still what the receipt
said.

**"What you paid last time" belongs to the workspace, not the note.**
Notes are shared instance-wide by access key — two people scanning the
same receipt get one row — so the comparison lives on `receipt_links`
alongside `not_my_purchase`. Migration `098` moved it there for that
reason.

## Data model

- `receipts`, `receipt_items`, `receipt_links`, `stores` (`097`)
- `products`, `product_aliases`, `price_points` (`098`), plus
  `receipt_items.product_id` and the workspace's `variation_summary`
- `receipt_capture_tokens` (`099`)

`receipts.status` is a state machine — `invalid, pending, fetching,
waiting_sefaz, authorized, parse_error, cancelled, gave_up` — with a
`status_reason` that names the cause in the words the UI shows. Retries
follow a fixed schedule (2 m → 24 h, eight attempts); a challenge or a
refused QR schedules nothing, because asking again the same way earns
the same answer.

Raw HTML of every page that could not be used is kept, gzipped, for 90
days. It is the only evidence of what a portal actually said, and it is
what let the ES parser be written against reality rather than against a
guess.

## What is not done

- **RJ adapter.** The QR parses and the state is recognised; the portal's
  page has not been read yet, so a note from there settles as
  `unsupported_uf`.
- **Automatic fetching anywhere.** No supported state currently answers
  the worker. The machinery is there and correct; it is waiting for a
  portal that will talk to it.
- **Linking a receipt to a transaction**, and anything on the dashboard.
