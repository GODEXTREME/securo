"""The bookmarklet's endpoint, and the tokens that authorise it.

`POST /api/receipt-capture` is the one route in the app that a page on
another origin may call. Two consequences shape it:

  * It cannot rely on the session cookie, so it authenticates with a
    capture token carried in the body.
  * The request must not need a CORS preflight, or the portal's page
    would have to answer an OPTIONS it never asked for. A `text/plain`
    body is a "simple request", so the browser sends it straight away —
    which is why the body is parsed by hand rather than by a model.

The response carries `Access-Control-Allow-Origin` only for the state
portals the adapters know, so the bookmarklet can read its own result
and nothing else can.
"""
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_writable_workspace
from app.receipts.adapters.registry import ADAPTERS
from app.schemas.receipt import ReceiptRead
from app.schemas.receipt_capture import CaptureResponse, CaptureTokenCreate, CaptureTokenCreated, CaptureTokenRead
from app.services import capture_service, receipt_service

logger = logging.getLogger(__name__)

#: Its own prefix, not a branch of /api/receipts: that router owns
#: `/{receipt_id}`, which would swallow every path segment here and answer
#: 422 for a name that is not a UUID. Matching order would decide it
#: otherwise, and nothing in the code would say so.
router = APIRouter(prefix="/api/receipt-capture", tags=["receipts"])

#: 2 MB of HTML, the same ceiling the paste endpoint has.
MAX_BODY = 2_000_000


def _portal_origins() -> frozenset[str]:
    """Every origin a supported portal is served from, in both schemes.
    The adapters' allowlist already decides which hosts are portals; this
    is the same set, written as origins."""
    origins: set[str] = set()
    for adapter in ADAPTERS.values():
        for host in adapter.allowed_hosts:
            origins.add(f"https://{host}")
            origins.add(f"http://{host}")
    return frozenset(origins)


def _allow_origin(response: Response, origin: Optional[str]) -> None:
    if origin and origin in _portal_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"


@router.post("", response_model=CaptureResponse)
async def capture_receipt(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
):
    _allow_origin(response, request.headers.get("origin"))
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail={"code": "too_large"})
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        secret = str(payload["token"])
        html = str(payload["html"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "bad_body"}) from None
    if not html.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "bad_body"})

    token = await capture_service.resolve_token(session, secret)
    if token is None:
        # Deliberately the same answer for an unknown, a revoked and a
        # malformed token: none of them should tell an attacker which.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "bad_token"})

    try:
        receipt = await capture_service.capture(session, token, html)
    except receipt_service.ReceiptError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": exc.code}) from exc

    link = await receipt_service.get_link(session, token.workspace_id, receipt.id)
    assert link is not None
    return CaptureResponse(receipt=ReceiptRead.from_pair(receipt, link))


@router.options("")
async def capture_preflight(request: Request, response: Response):
    """Only reached if a browser decides to preflight after all — a stricter
    setting, an extra header. Answering it costs nothing and keeps the
    bookmarklet working there too."""
    _allow_origin(response, request.headers.get("origin"))
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "86400"
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(response.headers))


@router.get("/tokens", response_model=list[CaptureTokenRead])
async def list_capture_tokens(
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    tokens = await capture_service.list_tokens(session, ctx.workspace.id, ctx.user_id)
    return [CaptureTokenRead.model_validate(token) for token in tokens]


@router.post("/tokens", response_model=CaptureTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_capture_token(
    data: CaptureTokenCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    token, secret = await capture_service.create_token(
        session, ctx.workspace.id, ctx.user_id, label=data.label
    )
    return CaptureTokenCreated(token=CaptureTokenRead.model_validate(token), secret=secret)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_capture_token(
    token_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        await capture_service.revoke_token(session, ctx.workspace.id, ctx.user_id, token_id)
    except receipt_service.ReceiptError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
