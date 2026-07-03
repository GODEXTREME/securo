"""Tests for batch-5 finance features: cash-vs-installments, dividend/income
tracking and the emergency-fund tracker."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.transaction import Transaction
from app.schemas.asset_income import AssetIncomeCreate
from app.schemas.emergency_fund import EmergencyFundUpdate
from app.services import asset_income_service, emergency_fund_service, purchase_service

TODAY = date.today()


async def _asset(session, user, ws, name="PETR4", invested=1000.0):
    a = Asset(id=uuid.uuid4(), user_id=user.id, workspace_id=ws.id, name=name, type="investment",
              currency="BRL", purchase_price=Decimal(str(invested)), purchase_price_primary=Decimal(str(invested)))
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


async def _tx(session, user, ws, account, amount, ttype="debit", d=None):
    session.add(Transaction(
        id=uuid.uuid4(), user_id=user.id, workspace_id=ws.id, account_id=account.id,
        category_id=None, description="x", amount=Decimal(str(amount)),
        currency=account.currency, date=d or TODAY, effective_date=d or TODAY, type=ttype,
        source="manual", status="posted", created_at=datetime.now(timezone.utc),
    ))
    await session.commit()


# --- Cash vs installments -------------------------------------------------

def test_cash_vs_installments_cash_wins():
    out = purchase_service.compare(cash_price=900, installment_total=1000, n_installments=10,
                                   investment_rate=12, rate_period="annual")
    # 10× 100 discounted at ~0.95%/mo has PV ~960 > 900 paid in cash today.
    assert out["cheaper"] == "cash"
    assert 50 < out["savings"] < 70
    assert out["pv_installments"] < out["installment_total"]
    assert out["per_installment"] == 100.0


def test_cash_vs_installments_installments_win_when_no_discount():
    # No cash discount (same price) → keeping money invested makes instalments win.
    out = purchase_service.compare(cash_price=1000, installment_total=1000, n_installments=12,
                                   investment_rate=12, rate_period="annual")
    assert out["cheaper"] == "installments"


@pytest.mark.asyncio
async def test_cash_vs_installments_api(client, auth_headers):
    r = await client.post("/api/purchase/cash-vs-installments",
                          json={"cash_price": 950, "installment_total": 1000,
                                "n_installments": 10, "investment_rate": 12},
                          headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["cheaper"] in ("cash", "installments")


# --- Dividends / asset income ---------------------------------------------

@pytest.mark.asyncio
async def test_asset_income_summary(session: AsyncSession, test_user, test_workspace):
    asset = await _asset(session, test_user, test_workspace, "HGLG11", invested=1000.0)
    await asset_income_service.create_income(session, test_workspace.id, test_user.id,
        AssetIncomeCreate(asset_id=asset.id, date=TODAY, amount=Decimal("50"), kind="rent"))
    await asset_income_service.create_income(session, test_workspace.id, test_user.id,
        AssetIncomeCreate(asset_id=asset.id, date=TODAY, amount=Decimal("30"), kind="dividend"))

    s = await asset_income_service.summary(session, test_workspace.id, test_user.id, months=12)
    assert s["total"] == 80.0
    by = s["by_asset"][0]
    assert by["name"] == "HGLG11"
    assert by["total"] == 80.0
    assert by["invested"] == 1000.0
    assert by["yield_pct"] == 8.0  # 80 / 1000
    assert len(s["series"]) == 12


@pytest.mark.asyncio
async def test_asset_income_api(client, auth_headers, session, test_user, test_workspace):
    asset = await _asset(session, test_user, test_workspace, "AAPL", invested=500.0)
    r = await client.post("/api/asset-income",
                          json={"asset_id": str(asset.id), "date": TODAY.isoformat(),
                                "amount": 12.5, "kind": "dividend"},
                          headers=auth_headers)
    assert r.status_code == 201
    r = await client.get("/api/asset-income", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()) == 1
    r = await client.get("/api/asset-income/summary?months=6", headers=auth_headers)
    assert r.status_code == 200 and r.json()["total"] == 12.5


# --- Emergency fund -------------------------------------------------------

@pytest.mark.asyncio
async def test_emergency_fund(session: AsyncSession, test_user, test_workspace, test_account):
    # ~1500/mo of expenses this month.
    await _tx(session, test_user, test_workspace, test_account, -1500)

    ef = await emergency_fund_service.update(session, test_workspace.id, test_user.id, "BRL",
                                             EmergencyFundUpdate(target_months=6, current_amount=Decimal("1000"),
                                                                 monthly_contribution=Decimal("500")))
    assert ef.avg_monthly_expense > 0
    assert ef.target_amount == round(ef.target_months * ef.avg_monthly_expense, 2)
    assert ef.saved_amount == 1000.0
    assert ef.shortfall == round(max(0.0, ef.target_amount - 1000.0), 2)
    assert ef.shortfall > 0
    # With a 500/mo contribution the completion estimate is a positive integer.
    assert ef.months_to_complete is not None and ef.months_to_complete > 0


@pytest.mark.asyncio
async def test_emergency_fund_api(client, auth_headers):
    r = await client.get("/api/emergency-fund", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["target_months"] == 6  # default
    r = await client.put("/api/emergency-fund", json={"target_months": 12, "current_amount": 5000},
                         headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["target_months"] == 12
    assert r.json()["saved_amount"] == 5000.0
