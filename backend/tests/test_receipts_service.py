"""The receipt state machine against the database: scanning, idempotency,
every outcome of an attempt, the retry schedule, and the manual paths."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.receipt import Receipt, ReceiptLink
from app.models.store import Store
from app.models.workspace import Workspace, WorkspaceMember
from app.receipts.fetcher import Fetcher, MemoryGate
from app.receipts.qr import QrError
from app.services import receipt_service
from app.services.receipt_service import RETRY_SCHEDULE, ReceiptError

FIXTURE = Path(__file__).parent / "fixtures" / "nfce" / "es" / "synthetic_v2.html"
KEY = "32260800063960006050650050003784571128411294"
URL = f"http://app.sefaz.es.gov.br/ConsultaNFCe?p={KEY}|2|1|1|4020a74fad969d92f6bb16ba1a7b4a177771fb3e"
NOW = datetime(2026, 8, 14, 22, 0, tzinfo=timezone.utc)


async def _public(host: str) -> bool:
    return False


def _same_instant(a: datetime, b: datetime) -> bool:
    """SQLite hands `DateTime(timezone=True)` back naive; Postgres keeps the
    offset. Compare as instants either way."""
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return a == b


def _fetcher(handler: Callable[[httpx.Request], httpx.Response]) -> Fetcher:
    return Fetcher(MemoryGate(), min_interval_ms=0, transport=httpx.MockTransport(handler), resolver=_public)


def _serving(html: str, status: int = 200) -> Fetcher:
    return _fetcher(lambda req: httpx.Response(status, text=html))


@pytest.fixture
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
async def second_workspace(session: AsyncSession, test_user) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Other", kind="personal", created_by_user_id=test_user.id, default_currency="BRL")
    session.add(ws)
    await session.flush()
    session.add(WorkspaceMember(id=uuid.uuid4(), workspace_id=ws.id, user_id=test_user.id, role="owner"))
    await session.commit()
    return ws


# ---------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scan_queues_a_new_key_and_links_it(session, test_user, test_workspace):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    assert out.created and not out.already_linked
    r = out.receipt
    assert r.status == "pending" and r.attempts == 0
    assert r.next_attempt_at is not None and _same_instant(r.next_attempt_at, NOW)
    assert (r.uf, r.series, r.number, r.issuer_cnpj) == ("ES", 5, 378457, "00063960006050")
    assert r.qr_url == URL and r.qr_version == 200
    assert out.link.workspace_id == test_workspace.id and out.link.user_id == test_user.id


@pytest.mark.asyncio
async def test_scan_twice_is_the_same_receipt(session, test_user, test_workspace):
    first = await receipt_service.scan(session, test_workspace.id, test_user.id, URL)
    again = await receipt_service.scan(session, test_workspace.id, test_user.id, KEY)
    assert again.receipt.id == first.receipt.id
    assert not again.created and again.already_linked
    assert await session.scalar(select(Receipt).where(Receipt.access_key == KEY)) is not None
    count = len((await session.execute(select(ReceiptLink))).scalars().all())
    assert count == 1


@pytest.mark.asyncio
async def test_two_workspaces_share_one_receipt(session, test_user, test_workspace, second_workspace):
    a = await receipt_service.scan(session, test_workspace.id, test_user.id, URL)
    b = await receipt_service.scan(session, second_workspace.id, test_user.id, URL)
    assert a.receipt.id == b.receipt.id and not b.created and not b.already_linked
    links = (await session.execute(select(ReceiptLink))).scalars().all()
    assert {link.workspace_id for link in links} == {test_workspace.id, second_workspace.id}


@pytest.mark.asyncio
async def test_key_first_then_qr_keeps_the_signed_url(session, test_user, test_workspace):
    await receipt_service.scan(session, test_workspace.id, test_user.id, KEY)
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL)
    assert out.receipt.qr_url == URL and out.receipt.qr_version == 200


@pytest.mark.asyncio
async def test_unparseable_input_raises(session, test_user, test_workspace):
    with pytest.raises(QrError) as exc:
        await receipt_service.scan(session, test_workspace.id, test_user.id, "nada")
    assert exc.value.code == "unrecognized"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,reason",
    [
        (f"http://app.sefaz.es.gov.br/ConsultaNFCe?p={KEY}|2|2|1|x", "homolog"),
        (f"http://evil.example/ConsultaNFCe?p={KEY}|2|1|1|x", "unsupported_host"),
        # São Paulo key: valid, no adapter yet.
        ("35260800063960006050650050003784571128411297", "unsupported_uf"),
    ],
)
async def test_policy_rejections_are_persisted_as_invalid(session, test_user, test_workspace, payload, reason):
    from app.receipts.qr import access_key_check_digit

    if payload.startswith("35"):
        payload = payload[:43] + str(access_key_check_digit(payload[:43]))
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, payload)
    assert out.receipt.status == "invalid" and out.receipt.status_reason == reason
    assert out.receipt.next_attempt_at is None


# ---------------------------------------------------------------------------
# one attempt, every outcome
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_authorized_page_persists_everything(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(html), now=NOW, raw_ttl_days=90)
    assert r is not None and r.status == "authorized" and r.status_reason is None
    assert r.locked_at is None and r.next_attempt_at is None
    assert r.source == "sefaz_html" and r.parser_version == 2
    assert r.issued_on == datetime(2026, 8, 14).date()
    assert r.items_count == 4 and r.total == Decimal("42.01") and r.discount == Decimal("2.00")
    assert [i.ordinal for i in r.items] == [1, 2, 3, 4]
    assert r.items[1].quantity == Decimal("0.585") and r.items[1].unit == "KG"
    assert r.payments and r.payments[0]["type"] == "credit_card"
    assert r.customer_cpf_hash is not None and "12345678909" not in r.customer_cpf_hash
    assert r.raw_html is not None and r.raw_expires_at is not None
    assert _same_instant(r.raw_expires_at, NOW + timedelta(days=90))
    store = await session.get(Store, r.store_id)
    assert store is not None and store.cnpj == "00063960006050" and store.cnpj_root == "00063960"
    assert store.city == "VITORIA"
    notif = await session.scalar(select(Notification).where(Notification.type == "receipt_processed"))
    assert notif is not None and notif.workspace_id == test_workspace.id
    assert notif.link == f"/receipts/{r.id}"


@pytest.mark.asyncio
async def test_reprocessing_replaces_items_and_does_not_duplicate(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(html), now=NOW)
    # Force a second pass the way an improved parser would.
    receipt = await session.get(Receipt, out.receipt.id)
    assert receipt is not None
    receipt.status = "pending"
    await session.commit()
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(html), now=NOW)
    assert r is not None and len(r.items) == 4
    notifs = (await session.execute(select(Notification))).scalars().all()
    assert len(notifs) == 1, "dedup_key keeps one notification per receipt"


@pytest.mark.asyncio
async def test_not_published_follows_the_schedule_then_gives_up(session, test_user, test_workspace):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    fetcher = _serving("<html>Não foi possível localizar a NFC-e</html>")
    now = NOW
    for attempt, wait in enumerate(RETRY_SCHEDULE, start=1):
        r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=fetcher, now=now)
        assert r is not None
        assert r.status == "waiting_sefaz" and r.status_reason == "not_published"
        assert r.attempts == attempt
        assert r.next_attempt_at is not None and _same_instant(r.next_attempt_at, now + wait)
        now = now + wait
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=fetcher, now=now)
    assert r is not None and r.status == "gave_up" and r.next_attempt_at is None
    assert r.attempts == len(RETRY_SCHEDULE) + 1
    # ≈ 45 hours end to end, inside the 48 h the design allows.
    assert now - NOW < timedelta(hours=48)

    revived = await receipt_service.retry(session, test_workspace.id, out.receipt.id, now=now)
    assert revived is not None and revived.status == "pending" and revived.attempts == 0


@pytest.mark.asyncio
async def test_rate_limited_waits_briefly_without_spending_an_attempt(session, test_user, test_workspace):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving("", 429), now=NOW)
    assert r is not None and r.status == "waiting_sefaz" and r.status_reason == "rate_limited"
    assert r.attempts == 0 and r.next_attempt_at is not None
    assert _same_instant(r.next_attempt_at, NOW + timedelta(seconds=30))


@pytest.mark.asyncio
async def test_portal_down_counts_an_attempt(session, test_user, test_workspace):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving("x", 503), now=NOW)
    assert r is not None and r.status == "waiting_sefaz" and r.status_reason == "portal_down" and r.attempts == 1


@pytest.mark.asyncio
async def test_captcha_stops_automatic_retries_and_paste_resolves_it(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving("<div class='g-recaptcha'>"), now=NOW)
    assert r is not None and r.status == "waiting_sefaz" and r.status_reason == "captcha"
    assert r.next_attempt_at is None, "no automatic retry against a challenge"
    assert await receipt_service.due_receipt_ids(session, now=NOW + timedelta(days=1)) == []

    r = await receipt_service.submit_html(session, test_workspace.id, out.receipt.id, html, now=NOW)
    assert r.status == "authorized" and r.source == "pasted_html" and len(r.items) == 4


@pytest.mark.asyncio
async def test_pasted_page_that_is_not_the_note_is_refused(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    with pytest.raises(ReceiptError) as exc:
        await receipt_service.submit_html(session, test_workspace.id, out.receipt.id, "<html>nope</html>")
    assert exc.value.code == "page_error_page"
    other = html.replace(KEY[:4] + " " + KEY[4:8], "1111 1111", 1)
    with pytest.raises(ReceiptError) as exc:
        await receipt_service.submit_html(session, test_workspace.id, out.receipt.id, other)
    assert exc.value.code == "key_mismatch"


@pytest.mark.asyncio
async def test_cancelled_note(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    cancelled = html.replace("<body>", "<body><b>NFC-e CANCELADA</b>")
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(cancelled), now=NOW)
    assert r is not None and r.status == "cancelled" and r.status_reason == "cancelled_by_sefaz"
    with pytest.raises(ReceiptError):
        await receipt_service.retry(session, test_workspace.id, out.receipt.id)


@pytest.mark.asyncio
async def test_parse_error_keeps_the_page_and_reprocesses_from_it(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    broken = html.replace('<span class="totalNumb txtMax">42,01</span>', '<span class="totalNumb txtMax">1,00</span>')
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(broken), now=NOW)
    assert r is not None and r.status == "parse_error" and r.status_reason == "parser_failed"
    assert r.raw_html is not None and "total_mismatch" in (r.last_error or "")
    # An improved parser would find it via stale_parse_error_ids; here the
    # stored page is re-read without touching the portal at all.
    r.parser_version = 0
    await session.commit()
    assert await receipt_service.stale_parse_error_ids(session) == [r.id]
    calls = []
    r = await receipt_service.process_receipt(
        session, out.receipt.id, fetcher=_fetcher(lambda req: calls.append(req) or httpx.Response(200, text=html)), now=NOW
    )
    assert r is not None and calls == [], "reprocessing reads the stored page"
    assert r.status == "parse_error", "the stored page is still the broken one"


@pytest.mark.asyncio
async def test_a_claim_is_exclusive(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    receipt = await session.get(Receipt, out.receipt.id)
    assert receipt is not None
    receipt.status = "fetching"
    receipt.locked_at = NOW - timedelta(minutes=1)
    await session.commit()
    assert await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(html), now=NOW) is None
    # A lock older than LOCK_STALE belongs to a dead worker and is taken over.
    r = await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(html), now=NOW + timedelta(minutes=11))
    assert r is not None and r.status == "authorized"


@pytest.mark.asyncio
async def test_due_ids_cover_pending_waiting_and_stale_fetching(session, test_user, test_workspace):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    assert await receipt_service.due_receipt_ids(session, now=NOW) == [out.receipt.id]
    assert await receipt_service.due_receipt_ids(session, now=NOW - timedelta(seconds=1)) == []
    receipt = await session.get(Receipt, out.receipt.id)
    assert receipt is not None
    receipt.status = "fetching"
    receipt.locked_at = NOW - timedelta(hours=1)
    await session.commit()
    assert await receipt_service.due_receipt_ids(session, now=NOW) == [out.receipt.id]


@pytest.mark.asyncio
async def test_expire_raw_html(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(html), now=NOW, raw_ttl_days=1)
    assert await receipt_service.expire_raw_html(session, now=NOW) == 0
    assert await receipt_service.expire_raw_html(session, now=NOW + timedelta(days=2)) == 1
    receipt = await session.get(Receipt, out.receipt.id)
    assert receipt is not None
    await session.refresh(receipt)  # bulk UPDATE; the identity map is not synchronised
    assert receipt.raw_html is None and receipt.status == "authorized"


# ---------------------------------------------------------------------------
# the personal side
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_link_flags_and_item_correction(session, test_user, test_workspace, test_transactions, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(html), now=NOW)
    link = await receipt_service.update_link(session, test_workspace.id, out.receipt.id, not_my_purchase=True)
    assert link is not None and link.not_my_purchase
    link = await receipt_service.update_link(session, test_workspace.id, out.receipt.id, transaction_id=test_transactions[0].id)
    assert link is not None and link.transaction_id == test_transactions[0].id
    with pytest.raises(ReceiptError, match="transaction_not_found"):
        await receipt_service.update_link(session, test_workspace.id, out.receipt.id, transaction_id=uuid.uuid4())
    link = await receipt_service.update_link(session, test_workspace.id, out.receipt.id, clear_transaction=True)
    assert link is not None and link.transaction_id is None

    item = await receipt_service.update_item(session, test_workspace.id, out.receipt.id, 1, unit_price_corrected=Decimal("4.79"), now=NOW)
    assert item is not None and item.unit_price == Decimal("4.89") and item.effective_unit_price == Decimal("4.79")
    item = await receipt_service.update_item(session, test_workspace.id, out.receipt.id, 1, unit_price_corrected=None)
    assert item is not None and item.effective_unit_price == Decimal("4.89") and item.corrected_at is None


@pytest.mark.asyncio
async def test_unlink_keeps_the_receipt(session, test_user, test_workspace):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL)
    assert await receipt_service.unlink(session, test_workspace.id, out.receipt.id)
    assert not await receipt_service.unlink(session, test_workspace.id, out.receipt.id)
    assert await receipt_service.get_link(session, test_workspace.id, out.receipt.id) is None
    assert await session.get(Receipt, out.receipt.id) is not None


@pytest.mark.asyncio
async def test_list_filters(session, test_user, test_workspace, html):
    out = await receipt_service.scan(session, test_workspace.id, test_user.id, URL, now=NOW)
    pending = await receipt_service.list_receipts(session, test_workspace.id, pending_only=True)
    assert [r.id for r, _ in pending] == [out.receipt.id]
    await receipt_service.process_receipt(session, out.receipt.id, fetcher=_serving(html), now=NOW)
    assert await receipt_service.list_receipts(session, test_workspace.id, pending_only=True) == []
    done = await receipt_service.list_receipts(session, test_workspace.id, status="authorized")
    assert len(done) == 1 and done[0][1].workspace_id == test_workspace.id
