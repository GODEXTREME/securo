# Fixtures — Rio de Janeiro (cUF 33)

`33260942591651053859650220000294281073101411.html` — **real**, captured
2026-09-07 from `consultadfe.fazenda.rj.gov.br`. The consumer's CPF is
masked; nothing else is touched.

It is the same shared tabResult template Espírito Santo serves, and the
parser read it unchanged on the first attempt. It is kept because it
exercises what the ES note does not: an emission timestamp carrying a
UTC offset, a protocol line with "às" between date and time, a real
itemised payment with change, and the approximate-taxes line.

Note the page's own complaint under "Informações para contribuinte e
fisco": the state's validator calls its own QR malformed ("A versão do
QR Code deve ser 2", "O Código do Hash do QR Code deve ter 40
caracteres") and serves the note regardless. That is why the parser
accepts a three-field payload — the alternative is refusing receipts
that Rio de Janeiro itself prints and answers.

## `cobranca-detalhada.html`

An excerpt — the payments panel — of Rio de Janeiro's **detailed** view
(`resultadoDfeDetalhado.faces`), captured 2026-09-09. It is here because
it is the counter-example that the field lookup needed: this XSLT puts
some values beside their label and others in a row *beneath* a row of
labels, and Rio de Janeiro uses the second form exactly where Goiás uses
the first. A parser that knows only one silently drops the payment.

Only the panel is kept; the rest of that page is the same markup the
Goiás fixture already exercises, and the note itself carries `SEM GTIN`
(it is fuel), so it would add nothing the other fixture does not.
