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

Two different walls, one shape: **neither of those two answers a server,
both answer the person.** That was the finding this feature was built
around — and it is a fact about Espírito Santo and Rio de Janeiro, not
about the country: Pernambuco and Goiás answer a plain request, one with
the XML and one with the note. It was expensive to establish — a "403" from a corporate proxy looks
exactly like a portal refusing you, and an IP-reputation block page turns
out to be a User-Agent filter.

We do not defeat either defence. A challenge is a request for a human,
and FlareSolverr-style solvers both fail against Turnstile today and
answer a question nobody asked us to answer.

### A state whose barcode is one page further in

Goiás puts a Cloudflare challenge on its **search form** and none on the
**QR route**. A plain request to `danfeNFCe?p=…` is answered — but with
the consumer DANFE, which has no barcode.

The barcode is on the page behind that one's "Visualizar NFC-e
detalhada" button: the national detailed view, the same tabbed XSLT Rio
de Janeiro reaches from its own key search. Asked for on its own it gets
the challenge; asked for on the client that was just served the note, it
answers. **The session is the credential.**

So an adapter can name a second URL (`follow_up`), and the fetcher —
which owns the client, the allowlist and the timeout — makes the
request. The URL is built from a page the portal wrote, so it is user
input by another name and gets the same host check the first one did. A
follow-up that fails keeps the first page: the receipt did arrive, only
the richer view did not.

`nfe_detail.py` holds that parser. Its markup is not in the page's DOM —
it arrives as an escaped JavaScript string handed to `new XmlNFE(...)` —
so it is unwrapped before anything is read, and a state that serves the
same markup directly needs no special case.

### A state that answers with the document

Pernambuco does not render a DANFE for the QR consultation. It answers
with the **authorised XML** — `procNFe` 4.00 inside its own envelope —
to a plain request, with no challenge and no browser.

That is a better source than any page, and the difference is not
cosmetic:

| | HTML DANFE (ES, RJ) | XML (PE) |
|---|---|---|
| barcode | absent | `det/prod/cEAN` |
| fiscal state | inferred from prose | `protNFe/infProt/cStat` |
| layout | a template a designer owns | a published schema |
| reachable by | a real browser | a plain request |

The barcode is the one that matters most. Everywhere else the catalogue
is stuck at chain-level identity — the same product in two chains cannot
be recognised as one — until a person scans it. In Pernambuco it arrives
with the note.

`nfe_xml.py` holds the parser, beside `tabresult.py` rather than inside
the state adapter, because the format is national: any state that serves
`procNFe` needs a binding and nothing more.

### The key route, where there is one

The signature at the end of a QR URL carries no check digit, so a single
character misread by the camera produces a well-formed URL the portal
refuses forever. The key itself is mod-11 checked, so it survives. When a
portal answers `QR_REJECTED`, the service therefore spends one more
request on the route built from the key alone.

That route is not universal, and the difference was measured, not assumed
(2026-09-07, a person driving a real browser):

| | key route | what it returns |
|---|---|---|
| Rio de Janeiro | `?p=<chave>\|3\|1` — the 3-field form | the DANFE |
| Espírito Santo | `?chNFe=<chave>` | an empty search form; the key must be typed behind the Turnstile |

`UFAdapter.key_route_answers` records which is which, and Espírito Santo
spends no request on a page that cannot answer. Where the route does
exist, only an authorised or cancelled note displaces the refusal: a form,
a challenge or a not-found says nothing about *this* receipt, and letting
a not-found through would schedule retries that cannot succeed.

Rio de Janeiro also has a fuller consultation at
`consultadfe.fazenda.rj.gov.br/consultaDFe` — the one reached from
`www.fazenda.rj.gov.br/nfce/consulta` — which works from the key with no
QR at all. It is a JSF form: the result URLs carry a `cid` conversation
id valid only inside the session that created it, so there is nothing to
fetch, only a form to drive. Not built.

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

## Fetching through a browser

Neither portal answers a request and both answer a browser. That is not
a guess: a real Chrome on the same network reaches the Rio de Janeiro
note, and everything that is not a browser does not. What was tried,
against the RJ note, before settling on this:

| | result |
|---|---|
| worker, identifying User-Agent | block page |
| worker, browser User-Agent | F5 interstitial |
| headless Chromium (Playwright) | navigation aborted |
| Trawl (FlareSolverr-compatible) | F5 interstitial, in 131 ms — it never ran a browser |
| FlareSolverr, against ES | "Error solving the challenge", 60 s timeout |
| a real browser, headful | **the note** |

So `BrowserFetcher` drives one over the Chrome DevTools Protocol: open a
tab, let the page's own scripts run, take the HTML, close the tab. The
browser is the operator's — a Kasm Chrome container is what this was
written against — which is what makes it defensible. Nothing defeats a
challenge. A challenge that wants a person is answered by a person, in
that browser, and the cookie their click leaves in the profile is what
the next fetch reuses.

It is **off unless configured** (`receipts_browser_cdp_url` and
`receipts_browser_ufs`). The browser ships as a compose service behind
the `receipts-browser` profile, so it exists only for instances that ask
for it — and its DevTools port is not published: whoever reaches that
port drives the browser, so it stays on the compose network. The screen
is published, because a challenge that wants a person needs a person to
see it.

The safety around it is unchanged: the host
allowlist is checked before the tab is opened — a browser follows
redirects and runs scripts, so that check matters more here, not less —
and the circuit breaker still speaks for the state.

### Keeping the browser alive across a redeploy

A persistent profile and a disposable container disagree. Chrome locks a
profile with the hostname and pid holding it, and refuses one locked by
"another computer" — which is what every recreated container looks like,
since Docker issues a fresh hostname each time. The browser then never
starts: the session relaunches it, it refuses again, and the log fills
with `Starting Chrome` while nothing listens on the DevTools port. From
outside, that is indistinguishable from a network fault: the forwarder
accepts the connection, fails to reach Chrome, and closes without a
response.

`hostname: kasm-chrome` fixes it. A stale lock then names this machine,
so Chrome checks the pid, finds it dead, and takes the profile back
instead of standing off against a computer it cannot ask.

### The browser spends the same token

A browser is a heavier client than a plain request, not a lighter one: it
loads the page, its images and its scripts. So it takes a token from the
same per-host bucket the HTTP fetcher uses, at the same interval. Without
that, re-importing a backlog arrives at the portal as fast as Chrome can
open tabs — which is the one situation where a person deliberately queues
many fetches at once.

A fetch the limiter turns away never reaches the portal, so it counts as
neither a success nor a failure against the state's circuit.

### Telling the tab where to go

`/json/new` takes the target as its **whole query string** — `PUT
/json/new?<percent-encoded url>` — not as a `url=` parameter. Sent the
obvious way, Chrome tries to navigate to the literal string
`url=https://…`, which is not a URL: the tab opens, never navigates, and
answers with an empty document. That reads exactly like a portal
returning nothing, and cost a round of looking in the wrong place.

### Knowing when the page has arrived

Opening a tab returns before the navigation does. A tab that has not
navigated reports `document.readyState === "complete"` for its own empty
document, so a fixed sleep followed by a read returns
`<html><head></head><body></body></html>` — which is what the first
working fetch stored as Rio de Janeiro's answer.

Waiting for *a* document is not enough either: the F5 interstitial is a
real page with real content that replaces itself once its script has run.
So the fetcher waits for **stillness**. It asks the tab what it holds —
URL and body length — and asks again a settle later; when the two answers
agree, the page is read. A portal that never settles hits the timeout
rather than returning half a page.

### Reaching the browser at all

The browser runs headful, because a challenge that wants a person needs
a person to see it. That choice costs two things, both found the hard
way against a real Chrome 149 (2026-09-08):

- **`--remote-debugging-port` is ignored on the default profile.** Since
  Chrome 136 the DevTools port is refused — silently, with no log and no
  `DevToolsActivePort` file — unless `--user-data-dir` names a
  non-default directory. The symptom is a browser that looks healthy and
  a port nothing listens on.
- **`--remote-debugging-address` is headless-only.** Passed to a headful
  Chrome it is accepted and disregarded: DevTools binds to `127.0.0.1`
  and stays there.

So the port is carried out of the browser's network namespace by a socat
sidecar running inside it (`network_mode: service:kasm-chrome`), and the
backend talks to `kasm-chrome:9223`. Chrome still only ever accepts a
connection from its own loopback, which is the property worth keeping.

Two consequences for the client. Chrome refuses a DevTools request whose
`Host` is neither localhost nor an IP — a name is exactly what arrives
through a forwarder — so `Host: localhost` is sent explicitly. And
Chrome echoes that Host back in the `webSocketDebuggerUrl` it reports,
which therefore says `localhost` and reaches nothing from here. That URL
is not rewritten: the Host it carries is the one Chrome accepts, so the
URL stays Chrome's and only the socket's destination is ours.

## What is not done

- **Minas Gerais and São Paulo.** Both answer a plain request with a
  challenge — Turnstile and reCAPTCHA — so both will need the browser,
  and neither has been read: a portal shows nothing without a real key,
  and none was available.
- **The barcode in Rio de Janeiro and Espírito Santo.** Their consumer
  DANFE does not carry one. Rio de Janeiro's detailed view does, but it
  is reachable only by driving the search form: four navigations per
  note, injecting script into the portal's page, against generated JSF
  ids. Weighed and declined — the note that prompted it turned out to be
  fuel, which has no barcode at all, and scanning one by hand on the
  product page covers Espírito Santo too and cannot break. The parser
  for that view exists (`nfe_detail.py`) if the decision is revisited.
- **Suggested product merges in the UI.** The backend computes them
  (`/suggestions`); nothing surfaces them, so a product is merged only
  by a barcode — scanned, or served by Pernambuco and Goiás.
