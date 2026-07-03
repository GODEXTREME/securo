"""API smoke tests for the calendar and sinking-funds endpoints."""
from datetime import date

import pytest


@pytest.mark.asyncio
async def test_calendar_api(client, auth_headers, test_workspace):
    today = date.today()
    r = await client.get(f"/api/calendar?year={today.year}&month={today.month}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["year"] == today.year and "daily" in body and "events" in body


@pytest.mark.asyncio
async def test_sinking_funds_api(client, auth_headers, test_workspace):
    # Empty list + summary.
    r = await client.get("/api/sinking-funds", headers=auth_headers)
    assert r.status_code == 200 and r.json() == []
    r = await client.get("/api/sinking-funds/summary", headers=auth_headers)
    assert r.status_code == 200

    # Create.
    r = await client.post("/api/sinking-funds", headers=auth_headers, json={
        "name": "Trip", "target_amount": "1000", "currency": "BRL",
    })
    assert r.status_code == 201, r.text
    fund = r.json()
    fund_id = fund["id"]

    # Contribute.
    r = await client.post(f"/api/sinking-funds/{fund_id}/contribute", headers=auth_headers, json={"amount": "250"})
    assert r.status_code == 200
    assert r.json()["current_amount"] == "250.00"
    assert r.json()["percentage"] == 25.0

    # Update.
    r = await client.patch(f"/api/sinking-funds/{fund_id}", headers=auth_headers, json={"name": "Trip 26"})
    assert r.status_code == 200 and r.json()["name"] == "Trip 26"

    # Delete.
    r = await client.delete(f"/api/sinking-funds/{fund_id}", headers=auth_headers)
    assert r.status_code == 204
