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
