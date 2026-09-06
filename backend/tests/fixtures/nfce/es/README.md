# Fixtures — Espírito Santo (cUF 32)

`32260800063960006050650050003784571128411294.html` — **real**, captured
2026-09-06: the page a browser renders after the Turnstile challenge
(saved via view-source and unwrapped). The consumer's CPF and the partner
line under "Informações de interesse do contribuinte" are masked. This is
the layout the parser targets.

`turnstile_challenge.html` — **real**, same date: what the portal answers
an automated request with. Must classify as CAPTCHA.

`synthetic_v2.html` — **hand-written** on the same template. Kept for the
paths the real note does not exercise: a discount line, a weighed item,
itemised payments with change. Retire it when a real note covers those.
