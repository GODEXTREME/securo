"""One adapter per state code. A state without an entry is `unsupported_uf`
at scan time — the user is told before anything is queued."""
from __future__ import annotations

from app.receipts.adapters.base import UFAdapter
from app.receipts.adapters.es import EsAdapter

ADAPTERS: dict[str, UFAdapter] = {
    EsAdapter.c_uf: EsAdapter(),
}


def adapter_for(c_uf: str) -> UFAdapter | None:
    return ADAPTERS.get(c_uf)


def supported_ufs() -> list[str]:
    return sorted(adapter.uf for adapter in ADAPTERS.values())
