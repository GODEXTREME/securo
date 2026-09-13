"""Where a note is looked up.

One answer, for the two callers that need it: the fetcher, which goes
there, and the screen, which offers it to a person as a link. They must
not disagree — a state where the deep link is dead (Espírito Santo) has
to send both to the form, or the app tells someone to open a page it
knows does not open.

Pure, and deliberately free of the ORM: it takes the four fields a
receipt keeps about its QR, so the schema can call it without importing
a service and the service can call it without going round the houses.
"""
from __future__ import annotations

from typing import Optional

from app.receipts.adapters.base import UFAdapter
from app.receipts.adapters.registry import ADAPTERS
from app.receipts.qr import QrPayload, parse_access_key


def payload_for(
    access_key: str, *, qr_url: Optional[str], qr_version: int, tp_amb: int
) -> QrPayload:
    """What the adapter is asked with. The signature and the token are
    left out: they live in the QR's URL, which is carried whole in
    `url`, and nothing rebuilds them from a key."""
    return QrPayload(
        key=parse_access_key(access_key),
        url=qr_url,
        version=qr_version,
        tp_amb=tp_amb,
        c_id_token=None,
        signature=None,
    )


def lookup_url(
    access_key: str,
    c_uf: str,
    *,
    qr_url: Optional[str],
    qr_version: int,
    tp_amb: int,
    adapters: dict[str, UFAdapter] = ADAPTERS,
) -> Optional[str]:
    """The page this note is consulted on, or None for a state with no
    adapter — where the app has nothing to offer and should say so
    rather than guess a portal."""
    adapter = adapters.get(c_uf)
    if adapter is None:
        return None
    return adapter.consulta_url(
        payload_for(access_key, qr_url=qr_url, qr_version=qr_version, tp_amb=tp_amb)
    )
