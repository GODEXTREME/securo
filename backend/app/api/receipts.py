import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace, current_writable_workspace
from app.receipts.adapters.registry import supported_ufs
from app.receipts.qr import QrError
from app.schemas.receipt import (
    ReceiptItemRead,
    ReceiptItemUpdate,
    ReceiptLinkUpdate,
    ReceiptRead,
    ScanRequest,
    ScanResponse,
    SubmitHtmlRequest,
    SupportedUfsRead,
)
from app.services import receipt_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


def _enqueue(receipt_id: uuid.UUID) -> None:
    """Hand the first attempt to the worker.

    Best effort by design: `retry=False` so an unreachable broker fails in
    milliseconds instead of holding the request through kombu's reconnect
    loop, and the failure is swallowed because the beat sweep dispatches
    anything still due within a minute. The user already has their answer
    ("received, fetching"); nothing here is worth a 5xx.
    """
    try:
        from app.tasks.receipt_tasks import fetch_receipt

        fetch_receipt.apply_async(args=[str(receipt_id)], retry=False)
    except Exception:
        logger.warning("could not dispatch fetch for receipt %s; sweep will", receipt_id, exc_info=True)


@router.get("/supported-ufs", response_model=SupportedUfsRead)
async def get_supported_ufs(ctx: WorkspaceContext = Depends(current_workspace)):
    return SupportedUfsRead(ufs=supported_ufs())


@router.post("/scan", response_model=ScanResponse, status_code=status.HTTP_201_CREATED)
async def scan_receipt(
    data: ScanRequest,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        outcome = await receipt_service.scan(session, ctx.workspace.id, ctx.user_id, data.payload)
    except QrError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": exc.code}
        ) from exc
    if outcome.created and outcome.receipt.status == "pending":
        _enqueue(outcome.receipt.id)
    return ScanResponse(
        receipt=ReceiptRead.from_pair(outcome.receipt, outcome.link),
        created=outcome.created,
        already_linked=outcome.already_linked,
    )


@router.get("", response_model=list[ReceiptRead])
async def list_receipts(
    status_filter: Optional[str] = Query(None, alias="status"),
    pending: bool = Query(False),
    store_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    pairs = await receipt_service.list_receipts(
        session, ctx.workspace.id, status=status_filter, pending_only=pending, store_id=store_id,
        date_from=date_from, date_to=date_to, limit=limit, offset=offset,
    )
    return [ReceiptRead.from_pair(receipt, link, with_items=False) for receipt, link in pairs]


@router.get("/{receipt_id}", response_model=ReceiptRead)
async def get_receipt(
    receipt_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    link = await receipt_service.get_link(session, ctx.workspace.id, receipt_id)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    return ReceiptRead.from_pair(link.receipt, link)


@router.post("/{receipt_id}/retry", response_model=ReceiptRead)
async def retry_receipt(
    receipt_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        receipt = await receipt_service.retry(session, ctx.workspace.id, receipt_id)
    except receipt_service.ReceiptError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": exc.code}) from exc
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    _enqueue(receipt.id)
    link = await receipt_service.get_link(session, ctx.workspace.id, receipt_id)
    assert link is not None
    return ReceiptRead.from_pair(receipt, link)


@router.post("/{receipt_id}/html", response_model=ReceiptRead)
async def submit_receipt_html(
    receipt_id: uuid.UUID,
    data: SubmitHtmlRequest,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        receipt = await receipt_service.submit_html(session, ctx.workspace.id, receipt_id, data.html)
    except receipt_service.ReceiptError as exc:
        if exc.code == "not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found") from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": exc.code}
        ) from exc
    link = await receipt_service.get_link(session, ctx.workspace.id, receipt_id)
    assert link is not None
    return ReceiptRead.from_pair(receipt, link)


@router.patch("/{receipt_id}", response_model=ReceiptRead)
async def update_receipt_link(
    receipt_id: uuid.UUID,
    data: ReceiptLinkUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        link = await receipt_service.update_link(
            session, ctx.workspace.id, receipt_id,
            not_my_purchase=data.not_my_purchase, transaction_id=data.transaction_id,
            clear_transaction=data.clear_transaction,
        )
    except receipt_service.ReceiptError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": exc.code}
        ) from exc
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    return ReceiptRead.from_pair(link.receipt, link)


@router.patch("/{receipt_id}/items/{ordinal}", response_model=ReceiptItemRead)
async def update_receipt_item(
    receipt_id: uuid.UUID,
    ordinal: int,
    data: ReceiptItemUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    item = await receipt_service.update_item(
        session, ctx.workspace.id, receipt_id, ordinal, unit_price_corrected=data.unit_price_corrected
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return ReceiptItemRead(
        id=item.id, ordinal=item.ordinal, product_code=item.product_code, gtin=item.gtin,
        description=item.description, ncm=item.ncm, cfop=item.cfop, unit=item.unit,
        quantity=item.quantity, unit_price=item.unit_price, total=item.total, discount=item.discount,
        unit_price_corrected=item.unit_price_corrected, effective_unit_price=item.effective_unit_price,
    )


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_receipt(
    receipt_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    if not await receipt_service.unlink(session, ctx.workspace.id, receipt_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
