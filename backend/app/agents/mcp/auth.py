from __future__ import annotations

import time
import uuid
from typing import Optional

from jose import jwt

from app.agents.config import get_agent_settings


JWT_ISSUER = "securo-backend"
JWT_AUDIENCE = "securo-mcp"
JWT_ALGO = "HS256"


def mint_token(
    *,
    user_id: uuid.UUID,
    conversation_id: Optional[uuid.UUID] = None,
    agent_id: Optional[uuid.UUID] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    s = get_agent_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "exp": now + (ttl_seconds or s.mcp_jwt_ttl_seconds),
    }
    if conversation_id:
        payload["conv_id"] = str(conversation_id)
    if agent_id:
        payload["agent_id"] = str(agent_id)
    return jwt.encode(payload, s.mcp_jwt_secret, algorithm=JWT_ALGO)
