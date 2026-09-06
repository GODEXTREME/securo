# Fixtures — Espírito Santo (cUF 32)

`turnstile_challenge.html` — **real**, captured 2026-09-06. What the portal
answers an automated request with: a Cloudflare Turnstile challenge. The
adapter must classify it as CAPTCHA.

`synthetic_v2.html` — **hand-written** against the shared "tabResult"
template the post-challenge DANFE is believed to use. It exercises every
selector the parser relies on, but no page from this portal has confirmed
the layout yet. Replace it with a real DANFE as soon as one is available:
open the QR URL in a browser, pass the challenge, save as "Web page,
complete", and drop the `.html` here named by its access key.
