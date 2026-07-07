"""Projection of not-yet-billed credit-card installments (read-only)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.services.dashboard_service import _add_months, _get_installment_projections

TODAY = date.today()
THIS_FIRST = TODAY.replace(day=1)
NEXT_FIRST = _add_months(THIS_FIRST, 1)
NEXT_END = _add_months(THIS_FIRST, 2)


async def _cc_account(session, user):
    acc = Account(
        id=uuid.uuid4(), user_id=user.id, name="Cartão", type="credit_card",
        balance=Decimal("0"), currency="BRL", statement_close_day=20, payment_due_day=28,
    )
    session.add(acc)
    await session.commit()
    await session.refresh(acc)
    return acc


async def _parcel(session, user, ws, acc, number, total, charge_date, per=100.0):
    session.add(Transaction(
        id=uuid.uuid4(), user_id=user.id, workspace_id=ws.id, account_id=acc.id,
        description="Geladeira", payee="Loja X", amount=Decimal(str(-per)), currency="BRL",
        date=charge_date, effective_date=charge_date, type="debit", source="sync", status="posted",
        installment_number=number, total_installments=total,
        installment_total_amount=Decimal(str(per * total)),
        installment_purchase_date=date(2025, 1, 15),
        created_at=datetime.now(timezone.utc),
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_projects_next_unbilled_parcel(session: AsyncSession, test_user, test_workspace):
    acc = await _cc_account(session, test_user)
    # Synced parcels 1/10..3/10; the last one is dated this month.
    await _parcel(session, test_user, test_workspace, acc, 1, 10, _add_months(THIS_FIRST, -2))
    await _parcel(session, test_user, test_workspace, acc, 2, 10, _add_months(THIS_FIRST, -1))
    await _parcel(session, test_user, test_workspace, acc, 3, 10, THIS_FIRST)

    # Next month should surface parcel 4/10 as a projection.
    projs = await _get_installment_projections(session, test_workspace.id, NEXT_FIRST, NEXT_END)
    assert len(projs) == 1
    p = projs[0]
    assert p["installment_number"] == 4
    assert p["total_installments"] == 10
    assert p["amount"] == 100.0
    assert p["type"] == "debit"
    assert NEXT_FIRST <= p["date"] < NEXT_END
    # Already-synced parcels are never projected.
    assert all(x["installment_number"] > 3 for x in projs)


@pytest.mark.asyncio
async def test_real_parcel_replaces_projection(session: AsyncSession, test_user, test_workspace):
    acc = await _cc_account(session, test_user)
    await _parcel(session, test_user, test_workspace, acc, 3, 10, THIS_FIRST)
    # Before the real 4/10 syncs, it's projected for next month.
    before = await _get_installment_projections(session, test_workspace.id, NEXT_FIRST, NEXT_END)
    assert [p["installment_number"] for p in before] == [4]

    # Once the real 4/10 lands, the projection for it disappears (max synced = 4),
    # so next month is empty (5/10 would fall the month after).
    await _parcel(session, test_user, test_workspace, acc, 4, 10, NEXT_FIRST)
    after = await _get_installment_projections(session, test_workspace.id, NEXT_FIRST, NEXT_END)
    assert after == []


@pytest.mark.asyncio
async def test_projection_strips_anchor_parcel_number(
    client, auth_headers, session, test_user, test_workspace
):
    # Provider embeds the parcel number in the payee ("… 2/10"). The projected
    # row must not carry that stale number — only the projected one.
    acc = await _cc_account(session, test_user)
    session.add(Transaction(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id, account_id=acc.id,
        description="Unidas Locadora - Parcela 2/10", payee="Unidas Locadora 2/10",
        amount=Decimal("-66.29"), currency="BRL", date=THIS_FIRST, effective_date=THIS_FIRST,
        type="debit", source="sync", status="posted",
        installment_number=2, total_installments=10,
        installment_total_amount=Decimal("662.90"), installment_purchase_date=date(2025, 5, 1),
        created_at=datetime.now(timezone.utc),
    ))
    await session.commit()
    r = await client.get(f"/api/dashboard/projected-transactions?month={NEXT_FIRST.isoformat()}", headers=auth_headers)
    inst = [p for p in r.json() if p.get("kind") == "installment"]
    assert len(inst) == 1
    assert inst[0]["installment_number"] == 3
    assert inst[0]["description"] == "Unidas Locadora 3/10"  # stripped anchor "2/10", projected "3/10"


@pytest.mark.asyncio
async def test_finished_plan_not_projected(session: AsyncSession, test_user, test_workspace):
    acc = await _cc_account(session, test_user)
    # Last parcel of a 3x plan already synced → nothing to project.
    await _parcel(session, test_user, test_workspace, acc, 3, 3, THIS_FIRST)
    projs = await _get_installment_projections(session, test_workspace.id, NEXT_FIRST, _add_months(THIS_FIRST, 6))
    assert projs == []


@pytest.mark.asyncio
async def test_projected_transactions_endpoint_includes_installment(
    client, auth_headers, session, test_user, test_workspace
):
    acc = await _cc_account(session, test_user)
    await _parcel(session, test_user, test_workspace, acc, 3, 10, THIS_FIRST)
    r = await client.get(f"/api/dashboard/projected-transactions?month={NEXT_FIRST.isoformat()}", headers=auth_headers)
    assert r.status_code == 200
    inst = [p for p in r.json() if p.get("kind") == "installment"]
    assert len(inst) == 1
    assert inst[0]["installment_number"] == 4
    assert inst[0]["description"].endswith("4/10")
    assert inst[0]["account_id"] == str(acc.id)
