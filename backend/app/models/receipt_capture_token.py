"""The credential a bookmarklet carries.

The portals of some states will not answer a server — Espírito Santo
serves a Cloudflare challenge, Rio de Janeiro an F5 script — but they
answer the person's own browser, which has already passed whatever was
asked. A bookmarklet run on the note's page reads the page and posts it
here, so the capture happens where the session already is.

That request cannot carry the app's session cookie: it leaves a page on
the state's origin, not ours. It carries one of these tokens instead —
scoped to a single workspace and a single endpoint, revocable, and
stored only as a hash, the way a password is.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReceiptCaptureToken(Base):
    __tablename__ = "receipt_capture_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: sha256 of the secret. The secret itself is shown once, when created.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    #: The first characters of the secret, so a person can tell two apart.
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
