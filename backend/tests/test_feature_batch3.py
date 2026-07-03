"""Tests for: what-if forecast, round-ups, saved searches, group budgets & streak."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.category_group import CategoryGroup
from app.models.transaction import Transaction
from app.schemas.budget import BudgetCreate
from app.services import (
    budget_extras_service,
    budget_service,
    forecast_service,
    roundup_service,
)

TODAY = date.today()
FIRST = TODAY.replace(day=1)


def _shift(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


async def _tx(session, user, ws, account, cat_id, amount, when, ttype="debit"):
    session.add(Transaction(
        id=uuid.uuid4(), user_id=user.id, workspace_id=ws.id, account_id=account.id,
        category_id=cat_id, description="x", amount=Decimal(str(amount)), currency=account.currency,
        date=when, effective_date=when, type=ttype, source="manual", status="posted",
        created_at=datetime.now(timezone.utc),
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_forecast_whatif(session: AsyncSession, test_user, test_workspace, test_account):
    base = await forecast_service.get_forecast(session, test_workspace.id, test_user.id, days=30)
    cut = await forecast_service.get_forecast(
        session, test_workspace.id, test_user.id, days=30, expense_adjust=300)
    extra = await forecast_service.get_forecast(
        session, test_workspace.id, test_user.id, days=30, income_adjust=300)
    # Cutting expenses raises the ending balance; extra income raises it more than baseline.
    assert cut["ending_balance"] > base["ending_balance"]
    assert extra["ending_balance"] > base["ending_balance"]


@pytest.mark.asyncio
async def test_roundups(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    await _tx(session, test_user, test_workspace, test_account, test_categories[0].id, -10.30, TODAY)
    await _tx(session, test_user, test_workspace, test_account, test_categories[0].id, -5.75, TODAY)
    r = await roundup_service.get_roundups(session, test_workspace.id, test_user.id, months=1)
    # 0.70 + 0.25 = 0.95
    assert r["transaction_count"] == 2
    assert abs(r["roundup_total"] - 0.95) < 0.001
    r2 = await roundup_service.get_roundups(session, test_workspace.id, test_user.id, months=1, multiplier=2)
    assert abs(r2["roundup_total"] - 1.90) < 0.001


@pytest.mark.asyncio
async def test_saved_searches_api(client, auth_headers, test_workspace):
    r = await client.get("/api/saved-searches", headers=auth_headers)
    assert r.status_code == 200 and r.json() == []
    r = await client.post("/api/saved-searches", headers=auth_headers,
                          json={"name": "Food last month", "filters_json": {"type": "debit"}})
    assert r.status_code == 201
    sid = r.json()["id"]
    r = await client.get("/api/saved-searches", headers=auth_headers)
    assert len(r.json()) == 1 and r.json()[0]["filters_json"] == {"type": "debit"}
    r = await client.delete(f"/api/saved-searches/{sid}", headers=auth_headers)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_group_budget_summary(session: AsyncSession, test_user, test_workspace, test_account):
    group = CategoryGroup(id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id, name="Living")
    session.add(group)
    await session.commit()
    cat = Category(id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id, name="Rent", group_id=group.id)
    session.add(cat)
    await session.commit()
    await budget_service.create_budget(session, test_workspace.id, test_user.id,
        BudgetCreate(category_id=cat.id, amount=Decimal("1000"), month=FIRST))
    await _tx(session, test_user, test_workspace, test_account, cat.id, -400, TODAY)

    summary = await budget_extras_service.group_summary(session, test_workspace.id, test_user.id, FIRST)
    living = next(g for g in summary["groups"] if g["name"] == "Living")
    assert living["budget"] == 1000.0 and living["actual"] == 400.0 and living["remaining"] == 600.0


@pytest.mark.asyncio
async def test_budget_streak(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    cat = test_categories[0]
    # Recurring budget of 500 effective 3 months ago.
    await budget_service.create_budget(session, test_workspace.id, test_user.id,
        BudgetCreate(category_id=cat.id, amount=Decimal("500"), month=_shift(FIRST, 3), is_recurring=True))
    # Spend under budget for the last 2 completed months.
    await _tx(session, test_user, test_workspace, test_account, cat.id, -200, _shift(FIRST, 1) + timedelta(days=2))
    await _tx(session, test_user, test_workspace, test_account, cat.id, -300, _shift(FIRST, 2) + timedelta(days=2))

    result = await budget_extras_service.get_streak(session, test_workspace.id, test_user.id)
    assert result["streak"] >= 2
