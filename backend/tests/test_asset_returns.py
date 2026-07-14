"""Asset returns (rendimento) — gain excluding contributions + window %."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.asset_income import AssetIncome
from app.models.asset_transaction import AssetTransaction
from app.models.asset_value import AssetValue
from app.services.asset_service import get_asset_returns

TODAY = date.today()
MONTH_T0 = TODAY.replace(day=1) - timedelta(days=1)
LAST_YEAR = date(TODAY.year - 1, 6, 1)


async def _asset(session, user, ws, name="CDB", type_="investment", currency="BRL",
                 purchase_price=None, purchase_date=None, valuation="manual"):
    a = Asset(
        id=uuid.uuid4(), user_id=user.id, workspace_id=ws.id, name=name, type=type_,
        currency=currency, valuation_method=valuation,
        purchase_price=purchase_price, purchase_date=purchase_date,
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


async def _value(session, asset, ws, d, amount):
    session.add(AssetValue(
        id=uuid.uuid4(), asset_id=asset.id, workspace_id=ws.id,
        amount=Decimal(str(amount)), date=d, source="manual",
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_gain_excludes_contributions(session: AsyncSession, test_user, test_workspace):
    # Bought for 1000 last year; worth 1100 today → gain 100 (10%), not 1100.
    a = await _asset(session, test_user, test_workspace,
                     purchase_price=Decimal("1000"), purchase_date=LAST_YEAR)
    await _value(session, a, test_workspace, LAST_YEAR, 1000)
    await _value(session, a, test_workspace, TODAY, 1100)

    out = await get_asset_returns(session, test_workspace.id, test_user.id)
    assert len(out["assets"]) == 1
    row = out["assets"][0]
    assert row["invested"] == 1000.0
    assert row["gain"] == 100.0
    assert row["pct_total"] == 10.0
    # Portfolio series ends at the same all-time gain.
    assert out["series"][-1]["gain"] == 100.0
    assert out["totals"]["gain"] == 100.0


@pytest.mark.asyncio
async def test_ledger_contribution_not_counted_as_yield(session: AsyncSession, test_user, test_workspace):
    # Value jumps 1000 → 1550, but 500 of that was a new buy → gain is 50.
    a = await _asset(session, test_user, test_workspace, valuation="manual",
                     purchase_price=Decimal("1000"), purchase_date=LAST_YEAR)
    await _value(session, a, test_workspace, LAST_YEAR, 1000)
    session.add(AssetTransaction(
        id=uuid.uuid4(), asset_id=a.id, workspace_id=test_workspace.id,
        kind="buy", quantity=Decimal("1"), price=Decimal("500"),
        fee=Decimal("0"), date=TODAY.replace(day=1), source="manual",
    ))
    await session.commit()
    await _value(session, a, test_workspace, TODAY, 1550)

    out = await get_asset_returns(session, test_workspace.id, test_user.id)
    row = out["assets"][0]
    # Ledger exists → basis comes only from the ledger (500), purchase_price ignored.
    assert row["invested"] == 500.0
    assert row["gain"] == 1050.0  # 1550 - 500 (purchase_price not in basis when ledger exists)


@pytest.mark.asyncio
async def test_income_counts_as_gain(session: AsyncSession, test_user, test_workspace):
    a = await _asset(session, test_user, test_workspace,
                     purchase_price=Decimal("1000"), purchase_date=LAST_YEAR)
    await _value(session, a, test_workspace, LAST_YEAR, 1000)
    await _value(session, a, test_workspace, TODAY, 1000)  # flat price...
    session.add(AssetIncome(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        asset_id=a.id, date=TODAY, amount=Decimal("30"), currency="BRL", kind="dividend",
    ))
    await session.commit()

    out = await get_asset_returns(session, test_workspace.id, test_user.id)
    row = out["assets"][0]
    assert row["income"] == 30.0
    assert row["gain"] == 30.0  # ...but the dividend is still a return
    assert row["pct_total"] == 3.0


@pytest.mark.asyncio
async def test_month_window_pct(session: AsyncSession, test_user, test_workspace):
    # Worth 1000 at the end of last month, 1010 today → +1% no mês.
    a = await _asset(session, test_user, test_workspace,
                     purchase_price=Decimal("900"), purchase_date=LAST_YEAR)
    await _value(session, a, test_workspace, LAST_YEAR, 900)
    await _value(session, a, test_workspace, MONTH_T0, 1000)
    await _value(session, a, test_workspace, TODAY, 1010)

    out = await get_asset_returns(session, test_workspace.id, test_user.id)
    row = out["assets"][0]
    assert row["pct_month"] == 1.0
    # All-time: (1010-900)/900
    assert row["pct_total"] == round(110 / 900 * 100, 2)


@pytest.mark.asyncio
async def test_no_basis_measures_from_first_snapshot(session: AsyncSession, test_user, test_workspace):
    # No purchase info and no ledger → baseline is the first snapshot.
    a = await _asset(session, test_user, test_workspace)
    await _value(session, a, test_workspace, LAST_YEAR, 2000)
    await _value(session, a, test_workspace, TODAY, 2200)

    out = await get_asset_returns(session, test_workspace.id, test_user.id)
    row = out["assets"][0]
    assert row["invested"] == 2000.0
    assert row["gain"] == 200.0
    assert row["pct_total"] == 10.0


@pytest.mark.asyncio
async def test_type_filter(session: AsyncSession, test_user, test_workspace):
    inv = await _asset(session, test_user, test_workspace, name="CDB", type_="investment")
    car = await _asset(session, test_user, test_workspace, name="Car", type_="vehicle")
    await _value(session, inv, test_workspace, TODAY, 100)
    await _value(session, car, test_workspace, TODAY, 50000)

    out = await get_asset_returns(session, test_workspace.id, test_user.id, types=["investment"])
    assert [a["name"] for a in out["assets"]] == ["CDB"]


@pytest.mark.asyncio
async def test_returns_endpoint(client, auth_headers, session, test_user, test_workspace):
    a = await _asset(session, test_user, test_workspace,
                     purchase_price=Decimal("1000"), purchase_date=LAST_YEAR)
    await _value(session, a, test_workspace, LAST_YEAR, 1000)
    await _value(session, a, test_workspace, TODAY, 1100)

    r = await client.get("/api/assets/returns?types=investment", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["gain"] == 100.0
    assert body["assets"][0]["pct_total"] == 10.0
    assert body["series"][-1]["gain"] == 100.0
