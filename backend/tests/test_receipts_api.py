"""The receipts routes over HTTP: the write gate, the link gate, and the
error codes the UI keys its messages on."""
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.receipts as receipts_api
from app.models.receipt import Receipt

FIXTURE = Path(__file__).parent / "fixtures" / "nfce" / "es" / "synthetic_v2.html"
KEY = "32260800063960006050650050003784571128411294"
URL = f"http://app.sefaz.es.gov.br/ConsultaNFCe?p={KEY}|2|1|1|4020a74fad969d92f6bb16ba1a7b4a177771fb3e"


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
    assert res.status_code == 200 and res.json() == {"ufs": ["ES"]}
