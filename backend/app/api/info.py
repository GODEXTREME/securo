"""Public capability/feature-flag endpoint.

Tells the frontend which optional features are enabled so it can hide
nav items, routes, etc. Lightweight — no auth required.
"""
import os

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["info"])


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


@router.get("/info")
async def get_app_info():
    return {
        "features": {
            "agents": _flag("AGENTS_ENABLED"),
            "tesouro_direto": _flag("TESOURO_DIRETO_ENABLED"),
        },
    }
