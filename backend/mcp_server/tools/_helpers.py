"""Shared helpers for serializing model rows into LLM-friendly dicts.

Keep payloads small and stable: a transaction returned to the LLM should
have a small set of obviously-named fields, not the full SQLAlchemy row.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional


def parse_date(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v))


def parse_uuid(v: Any) -> Optional[uuid.UUID]:
    if v is None or v == "":
        return None
    if isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


def parse_uuid_list(v: Any) -> Optional[list[uuid.UUID]]:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [parse_uuid(x) for x in v if x] or None
    return [parse_uuid(v)]


def num(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    return float(x)
