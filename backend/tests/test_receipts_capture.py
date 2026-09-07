"""The bookmarklet's path: a token that survives leaving our origin, and a
page that identifies itself.

The point of the whole mechanism is that the capture happens where the
browser session already is — so the tests exercise it the way the
bookmarklet does: a text/plain body, no session cookie, no receipt id.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.receipt import Receipt
from app.models.receipt_capture_token import ReceiptCaptureToken
from app.receipts.qr import find_access_key
from app.services import capture_service

ES = Path(__file__).parent / "fixtures" / "nfce" / "es"
REAL = ES / "32260800063960006050650050003784571128411294.html"
KEY = "32260800063960006050650050003784571128411294"
ORIGIN = "http://app.sefaz.es.gov.br"


async def _secret(client, auth_headers) -> str:
    res = await client.post("/api/receipt-capture/tokens", json={"label": "iPhone"}, headers=auth_headers)
    assert res.status_code == 201, res.text
    return res.json()["secret"]


async def _capture(client, secret: str, html: str, origin: str = ORIGIN):
    return await client.post(
        "/api/receipt-capture",
        content=json.dumps({"token": secret, "html": html}),
        headers={"Content-Type": "text/plain", "Origin": origin},
    )


class TestFindAccessKey:
    def test_reads_the_key_a_real_page_prints(self):
        key = find_access_key(REAL.read_text(encoding="utf-8"))
        assert key is not None and key.key == KEY

    def test_reads_it_grouped_in_fours(self):
        key = find_access_key("Chave de acesso: 3226 0800 0639 6000 6050 6500 5000 3784 5711 2841 1294")
        assert key is not None and key.key == KEY

    def test_refuses_a_run_of_digits_that_is_not_a_key(self):
        # 44 digits with a broken check digit: a coincidence, not a key.
        assert find_access_key("1" * 44) is None
        assert find_access_key("nada por aqui") is None


@pytest.mark.asyncio
async def test_capture_imports_a_note_never_scanned(client, auth_headers, session, test_workspace):
    secret = await _secret(client, auth_headers)
    res = await _capture(client, secret, REAL.read_text(encoding="utf-8"))
    assert res.status_code == 200, res.text
    receipt = res.json()["receipt"]
    assert receipt["access_key"] == KEY
    assert receipt["status"] == "authorized"
    assert receipt["source"] == "pasted_html"
    assert len(receipt["items"]) == 3
    # The bookmarklet must be able to read its own answer.
    assert res.headers.get("access-control-allow-origin") == ORIGIN


@pytest.mark.asyncio
async def test_capture_is_idempotent_on_the_same_note(client, auth_headers, session):
    secret = await _secret(client, auth_headers)
    html = REAL.read_text(encoding="utf-8")
    first = await _capture(client, secret, html)
    again = await _capture(client, secret, html)
    assert first.status_code == 200 and again.status_code == 200
    assert first.json()["receipt"]["id"] == again.json()["receipt"]["id"]
    rows = (await session.execute(select(Receipt).where(Receipt.access_key == KEY))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_page_without_a_key_is_refused(client, auth_headers):
    secret = await _secret(client, auth_headers)
    res = await _capture(client, secret, "<html><body>qualquer coisa</body></html>")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "no_access_key"


@pytest.mark.asyncio
async def test_the_challenge_page_is_named_as_such(client, auth_headers):
    """It carries the key — it is that note's page — but it is not the note.
    The answer has to say which, or a person cannot tell what went wrong."""
    secret = await _secret(client, auth_headers)
    res = await _capture(client, secret, (ES / "turnstile_challenge.html").read_text(encoding="utf-8"))
    assert res.status_code == 409 and res.json()["detail"]["code"] == "page_captcha"


@pytest.mark.asyncio
async def test_an_unknown_token_is_refused(client, auth_headers):
    res = await _capture(client, "nao-existe", REAL.read_text(encoding="utf-8"))
    assert res.status_code == 401 and res.json()["detail"]["code"] == "bad_token"


@pytest.mark.asyncio
async def test_a_revoked_token_stops_working(client, auth_headers, session):
    secret = await _secret(client, auth_headers)
    listed = await client.get("/api/receipt-capture/tokens", headers=auth_headers)
    assert listed.status_code == 200 and len(listed.json()) == 1
    token_id = listed.json()[0]["id"]
    assert listed.json()[0]["prefix"] == secret[: capture_service.PREFIX_LENGTH]

    gone = await client.delete(f"/api/receipt-capture/tokens/{token_id}", headers=auth_headers)
    assert gone.status_code == 204
    res = await _capture(client, secret, REAL.read_text(encoding="utf-8"))
    assert res.status_code == 401
    assert (await client.get("/api/receipt-capture/tokens", headers=auth_headers)).json() == []


@pytest.mark.asyncio
async def test_the_secret_is_never_stored(client, auth_headers, session):
    secret = await _secret(client, auth_headers)
    token = (await session.execute(select(ReceiptCaptureToken))).scalars().one()
    assert secret not in token.token_hash
    assert token.token_hash == capture_service.hash_token(secret)


@pytest.mark.asyncio
async def test_only_a_portal_origin_may_read_the_answer(client, auth_headers):
    secret = await _secret(client, auth_headers)
    res = await _capture(client, secret, REAL.read_text(encoding="utf-8"), origin="https://evil.example.com")
    assert res.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers}


@pytest.mark.asyncio
async def test_creating_a_token_needs_a_writable_workspace(client, viewer_auth_headers):
    res = await client.post("/api/receipt-capture/tokens", json={}, headers=viewer_auth_headers)
    assert res.status_code == 403
