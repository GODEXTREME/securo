"""API smoke tests for the new feature endpoints — verify routing/auth wiring
and basic response shape (business logic is covered in test_new_features.py)."""
import pytest


@pytest.mark.asyncio
async def test_notifications_api(client, auth_headers, test_workspace):
    r = await client.get("/api/notifications", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json() and "unread" in r.json()

    r = await client.post("/api/notifications/refresh", headers=auth_headers)
    assert r.status_code == 200
    assert "unread" in r.json()

    r = await client.get("/api/notifications/unread-count", headers=auth_headers)
    assert r.status_code == 200

    r = await client.post("/api/notifications/read-all", headers=auth_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_subscriptions_api(client, auth_headers, test_workspace):
    r = await client.get("/api/subscriptions", headers=auth_headers)
    assert r.status_code == 200
    assert "subscriptions" in r.json()


@pytest.mark.asyncio
async def test_insights_api(client, auth_headers, test_workspace):
    r = await client.get("/api/insights", headers=auth_headers)
    assert r.status_code == 200
    assert "insights" in r.json()


@pytest.mark.asyncio
async def test_forecast_api(client, auth_headers, test_workspace):
    r = await client.get("/api/forecast?days=30", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["days"] == 30


@pytest.mark.asyncio
async def test_health_score_api(client, auth_headers, test_workspace):
    r = await client.get("/api/health-score", headers=auth_headers)
    assert r.status_code == 200
    assert 0 <= r.json()["score"] <= 100


@pytest.mark.asyncio
async def test_debt_api(client, auth_headers, test_workspace):
    r = await client.get("/api/debt/accounts", headers=auth_headers)
    assert r.status_code == 200
    r = await client.post("/api/debt/plan", headers=auth_headers, json={"extra_payment": 100})
    assert r.status_code == 200
    assert "snowball" in r.json() and "avalanche" in r.json()


@pytest.mark.asyncio
async def test_installments_api(client, auth_headers, test_workspace):
    r = await client.get("/api/installments", headers=auth_headers)
    assert r.status_code == 200
    assert "plans" in r.json()


@pytest.mark.asyncio
async def test_advanced_reports_api(client, auth_headers, test_workspace):
    for path in ("/api/reports/merchants", "/api/reports/category-trends", "/api/reports/period-comparison"):
        r = await client.get(path, headers=auth_headers)
        assert r.status_code == 200, path
