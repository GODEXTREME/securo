from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import payee_service
from mcp_server.auth import CallContext
from mcp_server.registry import tool


@tool(
    name="list_payees",
    description="List the user's payees (merchants/counterparties).",
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    tags=["read", "payees"],
)
async def list_payees(
    *,
    session: AsyncSession,
    ctx: CallContext,
) -> dict[str, Any]:
    payees = await payee_service.get_payees(session, ctx.user_id)
    items = [
        {
            "id": str(p.id),
            "name": p.name,
            "default_category_id": str(p.default_category_id) if getattr(p, "default_category_id", None) else None,
        }
        for p in payees
    ]
    return {"items": items, "total": len(items)}
