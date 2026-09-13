# Fixtures — São Paulo (cUF 35)

`35260907128576000420650100001042781002063709.html` — **real**, captured
2026-09-13 from `www.nfce.fazenda.sp.gov.br`.

This is the consumer DANFE the QR leads to, and it is the shared ENCAT
`tabResult` template — the same one Espírito Santo and Rio de Janeiro
serve. It is kept as the evidence that São Paulo needs no parser of its
own: `parse_tabresult` reads it unchanged.

It is also the evidence against what the design notes used to say. They
had São Paulo down as guarded by a reCAPTCHA, recorded before anyone had
a real key to ask with. Asked with the signature its QR carries, the
portal answers a plain request with the note.

Ten items, one of them weighed (`0,258 KG`), a discount line, and a
single card payment — enough for the totals to have to add up rather
than trivially agree.

## What was trimmed

Script and style tags, which the parser never reads, and the values of
ASP.NET's `__VIEWSTATE`, `__VIEWSTATEGENERATOR` and `__EVENTVALIDATION`
inputs: postback state, session-scoped and long expired, with nothing of
the note in it. The inputs themselves stay, because their presence is
part of what this page looks like.

## What was masked

Nothing. The issuer is a business, and this note names no consumer — no
CPF, no name, no address. `parse` returns `customer_cpf` as None, which
is what the tests assert.
