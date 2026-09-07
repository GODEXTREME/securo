"""Capture tokens and the capture itself.

A bookmarklet on the state portal's page posts what the browser already
has. Two things make that possible: a credential that survives leaving
our origin (`ReceiptCaptureToken`), and a way for the note to identify
itself, since the bookmarklet knows nothing about it — the DANFE prints
its own access key, so the page says which receipt it is.

The capture therefore works whether or not the QR was ever scanned: an
unknown key becomes a receipt on the spot.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.receipt import Receipt, ReceiptLink
from app.models.receipt_capture_token import ReceiptCaptureToken
from app.receipts.adapters.registry import ADAPTERS
from app.receipts.pasted import normalize_pasted
from app.receipts.qr import find_access_key
from app.services import receipt_service
from app.services.receipt_service import ReceiptError

#: Long enough that guessing is hopeless, short enough to sit in a
#: bookmark's URL without wrapping.
TOKEN_BYTES = 24
PREFIX_LENGTH = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


async def create_token(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: Optional[str] = None,
    now: Optional[datetime] = None,
) -> tuple[ReceiptCaptureToken, str]:
    """Returns the row and the secret. The secret is never stored, so this
    is the only moment it can be shown."""
    secret = secrets.token_urlsafe(TOKEN_BYTES)
    token = ReceiptCaptureToken(
        workspace_id=workspace_id,
        user_id=user_id,
        token_hash=hash_token(secret),
        prefix=secret[:PREFIX_LENGTH],
        label=label,
        created_at=now or _now(),
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return token, secret


async def list_tokens(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> list[ReceiptCaptureToken]:
    result = await session.execute(
        select(ReceiptCaptureToken)
        .where(
            ReceiptCaptureToken.workspace_id == workspace_id,
            ReceiptCaptureToken.user_id == user_id,
            ReceiptCaptureToken.revoked_at.is_(None),
        )
        .order_by(ReceiptCaptureToken.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_token(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, token_id: uuid.UUID
) -> None:
    token = await session.get(ReceiptCaptureToken, token_id)
    if token is None or token.workspace_id != workspace_id or token.user_id != user_id:
        raise ReceiptError("not_found")
    if token.revoked_at is None:
        token.revoked_at = _now()
        await session.commit()


async def resolve_token(session: AsyncSession, secret: str) -> Optional[ReceiptCaptureToken]:
    """The row a secret names, or None. Looked up by hash, so the secret
    never has to be compared against anything stored in the clear."""
    if not secret:
        return None
    token = await session.scalar(
        select(ReceiptCaptureToken).where(ReceiptCaptureToken.token_hash == hash_token(secret))
    )
    return token if token is not None and token.is_active else None


async def capture(
    session: AsyncSession,
    token: ReceiptCaptureToken,
    html: str,
    *,
    now: Optional[datetime] = None,
) -> Receipt:
    """Read a page the browser already had, into the token's workspace."""
    now = now or _now()
    html = normalize_pasted(html)
    key = find_access_key(html)
    if key is None:
        raise ReceiptError("no_access_key", "no access key on the page")
    if key.c_uf not in ADAPTERS:
        raise ReceiptError("unsupported_uf")

    receipt = await session.scalar(select(Receipt).where(Receipt.access_key == key.key))
    if receipt is None:
        # Captured before it was ever scanned: the page is the whole
        # introduction. No QR was read, so there is no signed URL to keep,
        # and no attempt is scheduled — the page is already in hand.
        receipt = Receipt(
            access_key=key.key,
            c_uf=key.c_uf,
            uf=key.uf,
            model=key.model,
            series=key.series,
            number=key.number,
            tp_amb=1,
            tp_emis=key.tp_emis,
            qr_version=0,
            issuer_cnpj=key.issuer_cnpj,
            qr_url=None,
            status="pending",
            status_reason=None,
            next_attempt_at=None,
            first_scanned_at=now,
        )
        session.add(receipt)
        await session.flush()

    link = await session.scalar(
        select(ReceiptLink).where(
            ReceiptLink.receipt_id == receipt.id, ReceiptLink.workspace_id == token.workspace_id
        )
    )
    if link is None:
        session.add(
            ReceiptLink(
                receipt_id=receipt.id,
                workspace_id=token.workspace_id,
                user_id=token.user_id,
                scanned_at=now,
            )
        )
    token.last_used_at = now
    await session.commit()

    return await receipt_service.submit_html(session, token.workspace_id, receipt.id, html, now=now)
