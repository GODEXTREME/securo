"""Tests for the category-breakdown (pie) report."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.category_group import CategoryGroup
from app.models.transaction import Transaction
from app.services import advanced_report_service

TODAY = date.today()


async def _tx(session, user, ws, account, category_id, amount):
    session.add(Transaction(
        id=uuid.uuid4(), user_id=user.id, workspace_id=ws.id, account_id=account.id,
        category_id=category_id, description="x", amount=Decimal(str(amount)),
        currency=account.currency, date=TODAY, effective_date=TODAY, type="debit",
        source="manual", status="posted", created_at=datetime.now(timezone.utc),
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_category_breakdown_rolls_up_to_groups(
    session: AsyncSession, test_user, test_workspace, test_account, test_categories
):
    # Group with a child category.
    group = CategoryGroup(id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id, name="Food")
    session.add(group)
    await session.commit()
    child = Category(id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
                     name="Groceries", group_id=group.id, color="#111111")
    session.add(child)
    await session.commit()

    # A child-of-group expense, a top-level (no group) expense, and an uncategorized one.
    await _tx(session, test_user, test_workspace, test_account, child.id, -100)
    await _tx(session, test_user, test_workspace, test_account, test_categories[0].id, -60)  # no group
    await _tx(session, test_user, test_workspace, test_account, None, -40)  # uncategorized

    result = await advanced_report_service.category_breakdown(
        session, test_workspace.id, test_user.id, months=1
    )
    assert result["total"] == 200.0
    by_name = {s["name"]: s for s in result["slices"]}
    # The child rolled up into its group "Food".
    assert "Food" in by_name and by_name["Food"]["total"] == 100.0 and by_name["Food"]["is_group"] is True
    # Uncategorized slice present.
    unc = next(s for s in result["slices"] if s["uncategorized"])
    assert unc["total"] == 40.0
    # Percentages sum to ~100.
    assert abs(sum(s["percentage"] for s in result["slices"]) - 100.0) < 0.5


@pytest.mark.asyncio
async def test_category_breakdown_api(client, auth_headers, test_workspace):
    r = await client.get("/api/reports/category-breakdown?months=1", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "slices" in body and "total" in body
    r = await client.get("/api/reports/category-breakdown?months=6&flow=income", headers=auth_headers)
    assert r.status_code == 200
