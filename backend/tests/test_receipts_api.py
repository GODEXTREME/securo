"""The receipts routes over HTTP: the write gate, the link gate, and the
error codes the UI keys its messages on."""
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.receipts as receipts_api
from app.models.receipt import Receipt

FIXTURE = Path(__file__).parent / "fixtures" / "nfce" / "es" / "synthetic_v2.html"
KEY = "32260800063960006050650050003784571128411294"
URL = f"http://app.sefaz.es.gov.br/ConsultaNFCe?p={KEY}|2|1|1|4020a74fad969d92f6bb16ba1a7b4a177771fb3e"
#: A second real key, for the tests that need two distinct notes.
OTHER_KEY = "32260900937804000111650030005622551021215415"


@pytest.fixture
def enqueued(monkeypatch):
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(receipts_api, "_enqueue", lambda rid: calls.append(rid))
    return calls


@pytest.mark.asyncio
async def test_scan_creates_and_dispatches(client, auth_headers, test_workspace, enqueued):
    res = await client.post("/api/receipts/scan", json={"payload": URL}, headers=auth_headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["created"] and not body["already_linked"]
    assert body["receipt"]["status"] == "pending" and body["receipt"]["number"] == 378457
    # The UI opens this in a browser tab when the portal wants a human.
    assert body["receipt"]["qr_url"] == URL
    assert enqueued == [uuid.UUID(body["receipt"]["id"])]

    again = await client.post("/api/receipts/scan", json={"payload": KEY}, headers=auth_headers)
    assert again.status_code == 201 and again.json()["already_linked"]
    assert len(enqueued) == 1, "a known key is not re-queued"


@pytest.mark.asyncio
async def test_scan_rejects_garbage_with_a_code(client, auth_headers, enqueued):
    res = await client.post("/api/receipts/scan", json={"payload": "isto não é uma nota"}, headers=auth_headers)
    assert res.status_code == 422 and res.json()["detail"] == {"code": "unrecognized"}
    res = await client.post("/api/receipts/scan", json={"payload": KEY[:-1] + "5"}, headers=auth_headers)
    assert res.json()["detail"] == {"code": "check_digit"} and enqueued == []


@pytest.mark.asyncio
async def test_viewer_cannot_scan(client, viewer_auth_headers, enqueued):
    res = await client.post("/api/receipts/scan", json={"payload": URL}, headers=viewer_auth_headers)
    assert res.status_code == 403 and enqueued == []


@pytest.mark.asyncio
async def test_get_is_gated_by_the_link(client, auth_headers, session: AsyncSession, test_user, test_workspace):
    # A receipt this workspace never scanned: exists, but 404 here.
    orphan = Receipt(access_key=KEY, c_uf="32", uf="ES", series=5, number=1, issuer_cnpj="00063960006050")
    session.add(orphan)
    await session.commit()
    res = await client.get(f"/api/receipts/{orphan.id}", headers=auth_headers)
    assert res.status_code == 404
    res = await client.get(f"/api/receipts/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_list_pending_and_detail(client, auth_headers, enqueued):
    created = (await client.post("/api/receipts/scan", json={"payload": URL}, headers=auth_headers)).json()
    rid = created["receipt"]["id"]
    res = await client.get("/api/receipts", params={"pending": "true"}, headers=auth_headers)
    assert res.status_code == 200 and [r["id"] for r in res.json()] == [rid]
    assert res.json()[0]["items"] == [], "the list is light; items come with the detail"
    res = await client.get(f"/api/receipts/{rid}", headers=auth_headers)
    assert res.status_code == 200 and res.json()["link"]["not_my_purchase"] is False


@pytest.mark.asyncio
async def test_retry_html_patch_and_delete(client, auth_headers, enqueued):
    rid = (await client.post("/api/receipts/scan", json={"payload": URL}, headers=auth_headers)).json()["receipt"]["id"]

    res = await client.post(f"/api/receipts/{rid}/retry", headers=auth_headers)
    assert res.status_code == 409 and res.json()["detail"] == {"code": "not_retryable"}

    res = await client.post(f"/api/receipts/{rid}/html", json={"html": "<html>nope</html>"}, headers=auth_headers)
    assert res.status_code == 422 and res.json()["detail"] == {"code": "page_error_page"}

    res = await client.post(f"/api/receipts/{rid}/html", json={"html": FIXTURE.read_text(encoding="utf-8")}, headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "authorized" and body["source"] == "pasted_html"
    assert len(body["items"]) == 4 and body["store"]["cnpj"] == "00063960006050"
    assert body["total"] == "42.01"

    res = await client.patch(f"/api/receipts/{rid}", json={"not_my_purchase": True}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["link"]["not_my_purchase"] is True

    res = await client.patch(f"/api/receipts/{rid}", json={"transaction_id": str(uuid.uuid4())}, headers=auth_headers)
    assert res.status_code == 422 and res.json()["detail"] == {"code": "transaction_not_found"}

    res = await client.patch(f"/api/receipts/{rid}/items/1", json={"unit_price_corrected": "4.79"}, headers=auth_headers)
    assert res.status_code == 200 and Decimal(res.json()["effective_unit_price"]) == Decimal("4.79")
    res = await client.patch(f"/api/receipts/{rid}/items/99", json={"unit_price_corrected": "1"}, headers=auth_headers)
    assert res.status_code == 404

    res = await client.delete(f"/api/receipts/{rid}", headers=auth_headers)
    assert res.status_code == 204
    assert (await client.get(f"/api/receipts/{rid}", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_supported_ufs(client, auth_headers):
    res = await client.get("/api/receipts/supported-ufs", headers=auth_headers)
    # Exact on purpose: this is the list the scanner shows, so a state
    # registered by accident should fail here rather than ship.
    assert res.status_code == 200 and res.json() == {"ufs": ["ES", "RJ"]}


class TestTransactionCandidates:
    """Which debits a note could be. The endpoint answers with the two
    numbers that justify each guess; deciding stays with a person."""

    async def _authorized(self, client, auth_headers) -> str:
        res = await client.post("/api/receipts/scan", json={"payload": URL}, headers=auth_headers)
        rid = res.json()["receipt"]["id"]
        read = await client.post(
            f"/api/receipts/{rid}/html", json={"html": FIXTURE.read_text(encoding="utf-8")}, headers=auth_headers
        )
        assert read.json()["status"] == "authorized"
        return rid

    async def _debit(self, session, test_workspace, test_account, test_user, description, amount, on):
        from app.models.transaction import Transaction

        txn = Transaction(
            id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
            account_id=test_account.id, description=description, amount=amount,
            date=on, effective_date=on, type="debit", source="manual",
        )
        session.add(txn)
        await session.commit()
        return txn

    @pytest.mark.asyncio
    async def test_ranks_the_exact_amount_first(
        self, client, auth_headers, session, test_workspace, test_account, test_user, enqueued
    ):
        rid = await self._authorized(client, auth_headers)
        issued = (await session.get(Receipt, uuid.UUID(rid))).issued_on
        # The note totals 42.01. A charge to the cent, one two days later
        # that is close, and one nobody would confuse it with.
        await self._debit(session, test_workspace, test_account, test_user, "MERCADO", Decimal("42.01"), issued)
        await self._debit(
            session, test_workspace, test_account, test_user, "OUTRO", Decimal("42.50"),
            issued + timedelta(days=2),
        )
        await self._debit(session, test_workspace, test_account, test_user, "LONGE", Decimal("980.00"), issued)

        res = await client.get(f"/api/receipts/{rid}/transaction-candidates", headers=auth_headers)
        assert res.status_code == 200, res.text
        found = res.json()["candidates"]
        assert [c["description"] for c in found] == ["MERCADO", "OUTRO"], "the unrelated amount is not a candidate"
        assert found[0]["amount_difference"] == "0.00" and found[0]["days_apart"] == 0
        assert found[1]["days_apart"] == 2

    @pytest.mark.asyncio
    async def test_a_debit_another_note_already_claims_is_not_offered(
        self, client, auth_headers, session, test_workspace, test_account, test_user, enqueued
    ):
        """One charge is one purchase. Offering it twice invites a link
        that quietly replaces a correct one."""
        rid = await self._authorized(client, auth_headers)
        issued = (await session.get(Receipt, uuid.UUID(rid))).issued_on
        txn = await self._debit(
            session, test_workspace, test_account, test_user, "MERCADO", Decimal("42.01"), issued
        )

        # A second real key, so this exercises the exclusion rather than
        # a scan that quietly fails.
        other = await client.post(
            "/api/receipts/scan", json={"payload": OTHER_KEY}, headers=auth_headers
        )
        assert other.status_code == 201, other.text
        claimed = await client.patch(
            f"/api/receipts/{other.json()['receipt']['id']}",
            json={"transaction_id": str(txn.id)}, headers=auth_headers,
        )
        assert claimed.status_code == 200, claimed.text

        res = await client.get(f"/api/receipts/{rid}/transaction-candidates", headers=auth_headers)
        assert [c["description"] for c in res.json()["candidates"]] == []

    @pytest.mark.asyncio
    async def test_a_note_with_no_total_has_no_candidates(self, client, auth_headers, enqueued):
        """Nothing to match on. Answering with the week's debits would be
        guessing dressed as a suggestion."""
        res = await client.post("/api/receipts/scan", json={"payload": URL}, headers=auth_headers)
        rid = res.json()["receipt"]["id"]
        got = await client.get(f"/api/receipts/{rid}/transaction-candidates", headers=auth_headers)
        assert got.status_code == 200 and got.json()["candidates"] == []


class TestSummary:
    """The panel's numbers. What it must never do is count a note this
    workspace said it did not buy, or a note the portal has not answered."""

    async def _authorized(self, client, auth_headers, payload: str) -> str:
        res = await client.post("/api/receipts/scan", json={"payload": payload}, headers=auth_headers)
        rid = res.json()["receipt"]["id"]
        read = await client.post(
            f"/api/receipts/{rid}/html", json={"html": FIXTURE.read_text(encoding="utf-8")}, headers=auth_headers
        )
        assert read.json()["status"] == "authorized"
        return rid

    @pytest.mark.asyncio
    async def test_counts_what_was_bought(self, client, auth_headers, enqueued):
        await self._authorized(client, auth_headers, URL)
        res = await client.get("/api/receipts/summary", headers=auth_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["receipts"] == 1
        assert Decimal(body["total_spent"]) == Decimal("42.01")
        assert body["stores"][0]["receipts"] == 1
        assert Decimal(body["stores"][0]["total"]) == Decimal("42.01")

    @pytest.mark.asyncio
    async def test_leaves_out_a_note_that_is_not_mine(self, client, auth_headers, enqueued):
        """It is on the instance because someone scanned it, not because
        this workspace bought it. Counting it would inflate every number
        on the panel."""
        rid = await self._authorized(client, auth_headers, URL)
        marked = await client.patch(f"/api/receipts/{rid}", json={"not_my_purchase": True}, headers=auth_headers)
        assert marked.status_code == 200

        body = (await client.get("/api/receipts/summary", headers=auth_headers)).json()
        assert body["receipts"] == 0 and Decimal(body["total_spent"]) == Decimal("0")
        assert body["stores"] == [] and body["movers"] == []

    @pytest.mark.asyncio
    async def test_leaves_out_a_note_still_waiting_on_the_portal(self, client, auth_headers, enqueued):
        """Its total is unknown, so it can only be counted as zero — which
        would read as a purchase that cost nothing."""
        await client.post("/api/receipts/scan", json={"payload": URL}, headers=auth_headers)
        body = (await client.get("/api/receipts/summary", headers=auth_headers)).json()
        assert body["receipts"] == 0

    @pytest.mark.asyncio
    async def test_the_window_is_the_window(self, client, auth_headers, session, enqueued):
        """The fixture's note is from August 2026; a one-day window ending
        today must not contain it."""
        await self._authorized(client, auth_headers, URL)
        wide = (await client.get("/api/receipts/summary?days=1825", headers=auth_headers)).json()
        narrow = (await client.get("/api/receipts/summary?days=1", headers=auth_headers)).json()
        assert wide["receipts"] == 1 and narrow["receipts"] == 0
