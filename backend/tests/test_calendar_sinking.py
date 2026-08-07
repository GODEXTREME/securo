"""Tests for the sinking funds and financial calendar features."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.schemas.sinking_fund import SinkingFundCreate, SinkingFundUpdate
from app.services import calendar_service, sinking_fund_service

TODAY = date.today()


def _add_months(d: date, months: int) -> date:
    y, m = d.year, d.month + months
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, 1)


@pytest.mark.asyncio
async def test_sinking_fund_crud_and_contribute(session: AsyncSession, test_user, test_workspace):
    target_date = _add_months(TODAY, 4)
    created = await sinking_fund_service.create_fund(
        session, test_workspace.id, test_user.id,
        SinkingFundCreate(name="Trip", target_amount=Decimal("2000"), currency="BRL", target_date=target_date),
    )
    assert created.percentage == 0
    # ~4 months to target, 2000 remaining → ~500/mo suggested.
    assert created.suggested_monthly and created.suggested_monthly > 0

    funds = await sinking_fund_service.list_funds(session, test_workspace.id)
    assert len(funds) == 1

    # Contribute 500 → 25%.
    updated = await sinking_fund_service.contribute(session, created.id, test_workspace.id, Decimal("500"))
    assert updated is not None
    assert updated.current_amount == Decimal("500")
    assert updated.percentage == 25.0

    # Withdraw more than balance clamps to 0.
    updated = await sinking_fund_service.contribute(session, created.id, test_workspace.id, Decimal("-1000"))
    assert updated is not None
    assert updated.current_amount == Decimal("0")

    # Fully fund → completed.
    updated = await sinking_fund_service.contribute(session, created.id, test_workspace.id, Decimal("2000"))
    assert updated is not None
    assert updated.status == "completed"
    assert updated.percentage == 100.0

    # Update name.
    renamed = await sinking_fund_service.update_fund(
        session, created.id, test_workspace.id, SinkingFundUpdate(name="Trip 2026"))
    assert renamed is not None
    assert renamed.name == "Trip 2026"

    summary = await sinking_fund_service.summary(session, test_workspace.id)
    assert "total_saved" in summary

    assert await sinking_fund_service.delete_fund(session, created.id, test_workspace.id)
    assert await sinking_fund_service.delete_fund(session, uuid.uuid4(), test_workspace.id) is False


@pytest.mark.asyncio
async def test_calendar(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    # An actual income + expense in the current month.
    for amt, ttype in [(3000, "credit"), (-200, "debit")]:
        session.add(Transaction(
            id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
            account_id=test_account.id, category_id=test_categories[0].id,
            description="tx", amount=Decimal(str(amt)), currency=test_account.currency,
            date=TODAY, effective_date=TODAY, type=ttype, source="manual", status="posted",
            created_at=datetime.now(timezone.utc),
        ))
    await session.commit()

    result = await calendar_service.get_calendar(session, test_workspace.id, test_user.id, TODAY.year, TODAY.month)
    assert result["year"] == TODAY.year and result["month"] == TODAY.month
    key = TODAY.isoformat()
    assert key in result["daily"]
    assert result["daily"][key]["income"] == 3000.0
    assert result["daily"][key]["expense"] == 200.0
    assert result["month_income"] == 3000.0
    assert "events" in result
