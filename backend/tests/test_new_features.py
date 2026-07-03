"""Tests for the feature batch: notifications, subscriptions, insights,
cash-flow forecast, financial health score, debt planner, advanced reports,
budget rollover and installment grouping.

Uses the BRL test fixtures so no FX conversion is exercised.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.schemas.budget import BudgetCreate
from app.services import (
    advanced_report_service,
    budget_service,
    debt_service,
    forecast_service,
    health_service,
    insight_service,
    installment_service,
    notification_service,
    subscription_service,
)

TODAY = date.today()
FIRST = TODAY.replace(day=1)


def _shift_month(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


async def _add_tx(session, user, workspace, account, category=None, *, amount, when, ttype="debit",
                  payee=None, description="Purchase", **extra):
    tx = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        workspace_id=workspace.id,
        account_id=account.id,
        category_id=category.id if category else None,
        description=description,
        payee=payee,
        amount=Decimal(str(amount)),
        currency=account.currency,
        date=when,
        effective_date=when,
        type=ttype,
        source="manual",
        status="posted",
        created_at=datetime.now(timezone.utc),
        **extra,
    )
    session.add(tx)
    await session.commit()
    return tx


async def _mk_account(session, user, workspace, **kwargs):
    acc = Account(
        id=uuid.uuid4(),
        user_id=user.id,
        workspace_id=workspace.id,
        name=kwargs.pop("name", "Acc"),
        type=kwargs.pop("type", "checking"),
        balance=Decimal(str(kwargs.pop("balance", 0))),
        currency=kwargs.pop("currency", "BRL"),
        **kwargs,
    )
    session.add(acc)
    await session.commit()
    return acc


# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notifications_generate_and_read(session: AsyncSession, test_user, test_workspace, test_categories):
    # Overdrawn account → low_balance critical.
    await _mk_account(session, test_user, test_workspace, name="Overdrawn", type="checking", balance=-50)
    # Large transaction in last few days.
    big_acc = await _mk_account(session, test_user, test_workspace, name="Main", type="checking", balance=1000)
    await _add_tx(session, test_user, test_workspace, big_acc, test_categories[0],
                  amount=-5000, when=TODAY - timedelta(days=1), description="Big buy")

    created = await notification_service.generate_for_workspace(session, test_workspace.id, test_user.id)
    assert created >= 1

    items, unread = await notification_service.list_notifications(session, test_workspace.id, test_user.id)
    assert len(items) >= 1
    assert unread == len(items)

    # Idempotent: a second pass creates nothing new (dedup).
    again = await notification_service.generate_for_workspace(session, test_workspace.id, test_user.id)
    assert again == 0

    ok = await notification_service.mark_read(session, items[0].id, test_workspace.id, test_user.id)
    assert ok
    assert await notification_service.unread_count(session, test_workspace.id, test_user.id) == unread - 1

    await notification_service.mark_all_read(session, test_workspace.id, test_user.id)
    assert await notification_service.unread_count(session, test_workspace.id, test_user.id) == 0

    assert await notification_service.delete_notification(session, items[0].id, test_workspace.id, test_user.id)


@pytest.mark.asyncio
async def test_subscription_detection(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    for k in range(3, -1, -1):
        await _add_tx(session, test_user, test_workspace, test_account, test_categories[0],
                      amount=-29.90, when=TODAY - timedelta(days=30 * k), payee="Netflix", description="NETFLIX")
    result = await subscription_service.summarize(session, test_workspace.id)
    assert result["count"] >= 1
    sub = result["subscriptions"][0]
    assert sub["frequency"] == "monthly"
    assert result["monthly_total"] > 0


@pytest.mark.asyncio
async def test_insights(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    await _add_tx(session, test_user, test_workspace, test_account, test_categories[0],
                  amount=-100, when=_shift_month(FIRST, 1) + timedelta(days=2), description="prev")
    await _add_tx(session, test_user, test_workspace, test_account, test_categories[0],
                  amount=-400, when=TODAY, description="cur")
    await _add_tx(session, test_user, test_workspace, test_account, None,
                  amount=3000, when=TODAY, ttype="credit", description="salary")
    data = await insight_service.get_insights(session, test_workspace.id, test_user.id)
    assert "insights" in data and "movers" in data and "savings_series" in data
    assert len(data["savings_series"]) == 6
    assert data["top_merchants"]


@pytest.mark.asyncio
async def test_forecast(session: AsyncSession, test_user, test_workspace, test_account):
    result = await forecast_service.get_forecast(session, test_workspace.id, test_user.id, days=30)
    assert result["days"] == 30
    assert len(result["series"]) == 31
    assert "lowest" in result


@pytest.mark.asyncio
async def test_health_score(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    await _add_tx(session, test_user, test_workspace, test_account, None,
                  amount=5000, when=TODAY - timedelta(days=10), ttype="credit", description="salary")
    await _add_tx(session, test_user, test_workspace, test_account, test_categories[0],
                  amount=-2000, when=TODAY - timedelta(days=5), description="rent")
    result = await health_service.get_health_score(session, test_workspace.id, test_user.id)
    assert 0 <= result["score"] <= 100
    assert result["band"] in ("excellent", "good", "fair", "poor")
    assert len(result["components"]) == 4


@pytest.mark.asyncio
async def test_debt_planner(session: AsyncSession, test_user, test_workspace):
    await _mk_account(session, test_user, test_workspace, name="Card A", type="credit_card",
                      balance=3000, apr=Decimal("24.0"), minimum_payment=Decimal("100"))
    await _mk_account(session, test_user, test_workspace, name="Card B", type="credit_card",
                      balance=1000, apr=Decimal("36.0"), minimum_payment=Decimal("50"))
    accounts = await debt_service.get_debt_accounts(session, test_workspace.id)
    assert len(accounts) == 2

    plan = await debt_service.plan(session, test_workspace.id, extra_payment=300)
    assert plan["total_balance"] == 4000
    assert plan["snowball"]["months"] > 0
    assert plan["avalanche"]["months"] > 0
    assert plan["recommended"] in ("snowball", "avalanche")
    # Avalanche should never cost more interest than snowball.
    assert plan["avalanche"]["total_interest"] <= plan["snowball"]["total_interest"] + 0.01


@pytest.mark.asyncio
async def test_advanced_reports(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    await _add_tx(session, test_user, test_workspace, test_account, test_categories[0],
                  amount=-50, when=TODAY, payee="Uber", description="ride")
    await _add_tx(session, test_user, test_workspace, test_account, test_categories[0],
                  amount=-80, when=_shift_month(FIRST, 1) + timedelta(days=1), payee="Uber", description="ride")

    merchants = await advanced_report_service.merchant_breakdown(session, test_workspace.id, test_user.id, months=3)
    assert any(m["merchant"] == "Uber" for m in merchants["merchants"])

    trends = await advanced_report_service.category_trends(session, test_workspace.id, test_user.id, months=3)
    assert len(trends["months"]) == 3

    comp = await advanced_report_service.period_comparison(session, test_workspace.id, test_user.id, months=1)
    assert "rows" in comp and comp["current_total"] >= 0


@pytest.mark.asyncio
async def test_budget_rollover(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    cat = test_categories[0]
    # Recurring rollover budget of 500.
    await budget_service.create_budget(
        session, test_workspace.id, test_user.id,
        BudgetCreate(category_id=cat.id, amount=Decimal("500"), month=_shift_month(FIRST, 1),
                     is_recurring=True, rollover=True),
    )
    # Spent only 200 last month → 300 should carry over.
    await _add_tx(session, test_user, test_workspace, test_account, cat,
                  amount=-200, when=_shift_month(FIRST, 1) + timedelta(days=3), description="prev spend")

    rows = await budget_service.get_budget_vs_actual(session, test_workspace.id, test_user.id, month=FIRST)
    row = next(r for r in rows if str(r.category_id) == str(cat.id))
    assert row.rollover is True
    assert row.carryover == Decimal("300")
    assert row.available == Decimal("800")  # 500 budget + 300 carryover


@pytest.mark.asyncio
async def test_installment_grouping(session: AsyncSession, test_user, test_workspace, test_categories):
    card = await _mk_account(session, test_user, test_workspace, name="Card", type="credit_card", balance=900)
    purchase = TODAY - timedelta(days=40)
    for n in range(1, 4):
        await _add_tx(session, test_user, test_workspace, card, None,
                      amount=-300, when=purchase + timedelta(days=30 * (n - 1)), description="TV STORE",
                      installment_number=n, total_installments=3,
                      installment_total_amount=Decimal("900"), installment_purchase_date=purchase)

    result = await installment_service.group_plans(session, test_workspace.id)
    assert result["count"] == 1
    plan = result["plans"][0]
    assert plan["total_installments"] == 3
    assert plan["paid_count"] == 3
    assert plan["total_amount"] == 900.0
    assert plan["uncategorized"] is True
    assert len(plan["transaction_ids"]) == 3

    # Categorizing the plan tags all three parcels.
    from app.services.transaction_service import bulk_update_category
    ids = [uuid.UUID(i) for i in plan["transaction_ids"]]
    count = await bulk_update_category(session, test_workspace.id, ids, test_categories[0].id)
    assert count == 3

    result2 = await installment_service.group_plans(session, test_workspace.id, only_uncategorized=True)
    assert result2["count"] == 0
