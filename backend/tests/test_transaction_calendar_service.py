import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.fx_rate import FxRate
from app.models.recurring_transaction import RecurringTransaction
from app.models.transaction import Transaction
from app.services.transaction_calendar_service import get_transaction_calendar


@pytest.mark.asyncio
async def test_transaction_calendar_combines_actual_projected_and_balances(
    session: AsyncSession, test_user, test_workspace
):
    account = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        name="Person",
        type="checking",
        balance=Decimal("0"),
        currency="BRL",
    )
    category = Category(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        name="Bills",
        icon="receipt",
        color="#f97316",
    )
    session.add_all([account, category])
    await session.flush()

    salary = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        account_id=account.id,
        category_id=category.id,
        description="Salary",
        amount=Decimal("1000"),
        currency="BRL",
        date=date(2026, 7, 2),
        type="credit",
        source="manual",
    )
    groceries = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        account_id=account.id,
        category_id=category.id,
        description="Groceries",
        amount=Decimal("200"),
        currency="BRL",
        date=date(2026, 7, 5),
        type="debit",
        source="manual",
    )
    rent = RecurringTransaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        account_id=account.id,
        category_id=category.id,
        description="Rent",
        amount=Decimal("300"),
        currency="BRL",
        type="debit",
        frequency="monthly",
        start_date=date(2026, 7, 10),
        next_occurrence=date(2026, 7, 10),
    )
    session.add_all([salary, groceries, rent])
    await session.commit()

    calendar = await get_transaction_calendar(
        session, test_workspace.id, test_user.id, month=date(2026, 7, 1)
    )

    assert calendar.month == "2026-07"
    assert calendar.currency == "BRL"
    assert calendar.days[0].date == date(2026, 6, 28)
    assert calendar.days[-1].date == date(2026, 8, 1)

    july_2 = next(day for day in calendar.days if day.date == date(2026, 7, 2))
    assert july_2.income == 1000.0
    assert july_2.ending_balance == 1000.0
    assert july_2.actual_count == 1
    assert july_2.items[0].kind == "actual"

    july_5 = next(day for day in calendar.days if day.date == date(2026, 7, 5))
    assert july_5.expense == 200.0
    assert july_5.ending_balance == 800.0

    july_10 = next(day for day in calendar.days if day.date == date(2026, 7, 10))
    assert july_10.projected_count == 1
    assert july_10.expense == 300.0
    assert july_10.ending_balance == 500.0
    assert july_10.items[0].kind == "projected"
    assert july_10.items[0].recurring_id == rent.id


@pytest.mark.asyncio
async def test_transaction_calendar_respects_account_filter(
    session: AsyncSession, test_user, test_workspace
):
    kept = Account(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="Kept", type="checking", balance=Decimal("0"), currency="BRL",
    )
    other = Account(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="Other", type="checking", balance=Decimal("0"), currency="BRL",
    )
    session.add_all([kept, other])
    await session.flush()
    session.add_all([
        Transaction(
            id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
            account_id=kept.id, description="Kept income", amount=Decimal("100"),
            currency="BRL", date=date(2026, 7, 3), type="credit", source="manual",
        ),
        Transaction(
            id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
            account_id=other.id, description="Other income", amount=Decimal("999"),
            currency="BRL", date=date(2026, 7, 3), type="credit", source="manual",
        ),
    ])
    await session.commit()

    calendar = await get_transaction_calendar(
        session,
        test_workspace.id,
        test_user.id,
        month=date(2026, 7, 1),
        account_ids=[kept.id],
    )

    july_3 = next(day for day in calendar.days if day.date == date(2026, 7, 3))
    assert july_3.income == 100.0
    assert july_3.ending_balance == 100.0
    assert [item.description for item in july_3.items] == ["Kept income"]


@pytest.mark.asyncio
async def test_transaction_calendar_single_foreign_account_uses_primary_currency_balance(
    session: AsyncSession, test_user, test_workspace
):
    account = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        name="USD checking",
        type="checking",
        balance=Decimal("0"),
        currency="USD",
    )
    session.add_all([
        account,
        FxRate(
            base_currency="USD",
            quote_currency="BRL",
            date=date.today(),
            rate=Decimal("5"),
            source="test",
        ),
    ])
    await session.flush()
    session.add_all([
        Transaction(
            id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
            account_id=account.id, description="Starting cash", amount=Decimal("100"),
            currency="USD", date=date(2026, 6, 20), type="credit", source="opening_balance",
        ),
        Transaction(
            id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
            account_id=account.id, description="Coffee", amount=Decimal("10"),
            currency="USD", date=date(2026, 7, 2), type="debit", source="manual",
        ),
    ])
    await session.commit()

    calendar = await get_transaction_calendar(
        session,
        test_workspace.id,
        test_user.id,
        month=date(2026, 7, 1),
        account_ids=[account.id],
    )

    assert calendar.currency == "BRL"
    july_1 = next(day for day in calendar.days if day.date == date(2026, 7, 1))
    assert july_1.ending_balance == 500.0
    july_2 = next(day for day in calendar.days if day.date == date(2026, 7, 2))
    assert july_2.expense == 50.0
    assert july_2.ending_balance == 450.0


@pytest.mark.asyncio
async def test_transaction_calendar_skips_closed_account_recurring_projections(
    session: AsyncSession, test_user, test_workspace
):
    closed_account = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        name="Closed",
        type="checking",
        balance=Decimal("0"),
        currency="BRL",
        is_closed=True,
    )
    session.add(closed_account)
    await session.flush()
    session.add(
        RecurringTransaction(
            id=uuid.uuid4(),
            user_id=test_user.id,
            workspace_id=test_workspace.id,
            account_id=closed_account.id,
            description="Old subscription",
            amount=Decimal("25"),
            currency="BRL",
            type="debit",
            frequency="monthly",
            start_date=date(2026, 7, 10),
            next_occurrence=date(2026, 7, 10),
        )
    )
    await session.commit()

    calendar = await get_transaction_calendar(
        session, test_workspace.id, test_user.id, month=date(2026, 7, 1)
    )

    july_10 = next(day for day in calendar.days if day.date == date(2026, 7, 10))
    assert july_10.projected_count == 0
    assert july_10.items == []
    assert july_10.ending_balance == 0.0
