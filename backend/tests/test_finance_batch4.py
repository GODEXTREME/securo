"""Tests for batch-4 finance features: loan simulator, FIRE projection,
cashback/rewards tracking and the fixed-income comparator."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.schemas.fixed_income import FixedIncomeOptionCreate
from app.schemas.reward import RewardRuleCreate
from app.services import fixed_income_service, loan_service, retirement_service, reward_service

TODAY = date.today()


async def _tx(session, user, ws, account, category_id, amount, ttype="debit"):
    session.add(Transaction(
        id=uuid.uuid4(), user_id=user.id, workspace_id=ws.id, account_id=account.id,
        category_id=category_id, description="x", amount=Decimal(str(amount)),
        currency=account.currency, date=TODAY, effective_date=TODAY, type=ttype,
        source="manual", status="posted", created_at=datetime.now(timezone.utc),
    ))
    await session.commit()


# --- Loan simulator -------------------------------------------------------

def test_loan_simulator_price_and_sac():
    out = loan_service.simulate(principal=12000, rate=12, months=12, rate_period="annual", method="both")
    price = out["results"]["price"]
    sac = out["results"]["sac"]
    assert price["months"] == 12 and sac["months"] == 12
    # Both fully amortize to zero.
    assert price["schedule"][-1]["balance"] == 0.0
    assert sac["schedule"][-1]["balance"] == 0.0
    # Price instalment is constant; SAC's first instalment is larger and it decreases.
    assert abs(price["schedule"][0]["payment"] - price["schedule"][-1]["payment"]) < 0.05
    assert sac["schedule"][0]["payment"] > sac["schedule"][-1]["payment"]
    # SAC pays less total interest, so it's recommended.
    assert sac["total_interest"] < price["total_interest"]
    assert out["recommended"] == "sac"


def test_loan_extra_payment_shortens_term():
    base = loan_service.simulate(principal=100000, rate=1, months=120, rate_period="monthly", method="price")
    faster = loan_service.simulate(principal=100000, rate=1, months=120, rate_period="monthly",
                                   method="price", extra_payment=500)
    assert faster["results"]["price"]["months"] < base["results"]["price"]["months"]


@pytest.mark.asyncio
async def test_loan_api(client, auth_headers):
    r = await client.post("/api/loans/simulate",
                          json={"principal": 50000, "rate": 14, "months": 48, "method": "both"},
                          headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "price" in body["results"] and "sac" in body["results"]
    assert body["results"]["price"]["total_interest"] > 0


# --- FIRE / retirement ----------------------------------------------------

def test_fire_projection_reaches_target():
    out = retirement_service.project(
        current_net_worth=100000, monthly_contribution=2000, annual_return=6,
        annual_expenses=48000, withdrawal_rate=4, current_age=30,
    )
    assert out["fire_number"] == 1200000.0  # 48000 / 4%
    assert out["reached"] is True
    assert out["years_to_fire"] and out["years_to_fire"] > 0
    assert out["age_at_fire"] and out["age_at_fire"] > 30
    assert 8.0 <= out["progress_pct"] <= 9.0  # 100k / 1.2M
    assert len(out["series"]) > 1


def test_fire_zero_contribution_may_not_reach():
    out = retirement_service.project(
        current_net_worth=1000, monthly_contribution=0, annual_return=0,
        annual_expenses=48000, withdrawal_rate=4,
    )
    assert out["reached"] is False
    assert out["years_to_fire"] is None


@pytest.mark.asyncio
async def test_retirement_api(client, auth_headers):
    r = await client.get("/api/retirement/defaults", headers=auth_headers)
    assert r.status_code == 200
    assert "current_net_worth" in r.json()
    r = await client.post("/api/retirement/project",
                          json={"monthly_contribution": 1500, "annual_return": 7,
                                "annual_expenses": 36000, "withdrawal_rate": 4},
                          headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["fire_number"] == 900000.0


# --- Cashback / rewards ---------------------------------------------------

@pytest.mark.asyncio
async def test_rewards_summary(session: AsyncSession, test_user, test_workspace, test_account, test_categories):
    # 5% back on category[0], 2% default on everything else for this card.
    await reward_service.create_rule(session, test_workspace.id, test_user.id,
                                      RewardRuleCreate(account_id=test_account.id,
                                                       category_id=test_categories[0].id, rate=Decimal("5")))
    await reward_service.create_rule(session, test_workspace.id, test_user.id,
                                     RewardRuleCreate(account_id=test_account.id, rate=Decimal("2")))
    await _tx(session, test_user, test_workspace, test_account, test_categories[0].id, -100)  # 5% -> 5
    await _tx(session, test_user, test_workspace, test_account, None, -100)  # default 2% -> 2

    s = await reward_service.summary(session, test_workspace.id, test_user.id, months=1)
    assert s["total_earned"] == 7.0
    assert s["total_spend"] == 200.0
    # Best card for category[0] is this card at 5%.
    best0 = next(b for b in s["best_per_category"] if b["category_id"] == str(test_categories[0].id))
    assert best0["rate"] == 5.0


@pytest.mark.asyncio
async def test_rewards_api(client, auth_headers, test_account, test_categories):
    r = await client.post("/api/rewards",
                          json={"account_id": str(test_account.id), "rate": 1.5, "name": "cashback"},
                          headers=auth_headers)
    assert r.status_code == 201
    r = await client.get("/api/rewards", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()) == 1
    r = await client.get("/api/rewards/summary?months=1", headers=auth_headers)
    assert r.status_code == 200 and "total_earned" in r.json()


# --- Fixed-income comparator ---------------------------------------------

@pytest.mark.asyncio
async def test_fixed_income_compare_tax_exempt_wins(
    session: AsyncSession, test_user, test_workspace
):
    await fixed_income_service.create_option(session, test_workspace.id, test_user.id,
        FixedIncomeOptionCreate(name="CDB Banco A", rate_kind="cdi", rate=Decimal("100"),
                                liquidity="daily", tax_exempt=False, product_type="CDB"))
    lci = await fixed_income_service.create_option(session, test_workspace.id, test_user.id,
        FixedIncomeOptionCreate(name="LCI Banco B", rate_kind="cdi", rate=Decimal("90"),
                                liquidity="daily", tax_exempt=True, product_type="LCI"))

    cmp = await fixed_income_service.compare(session, test_workspace.id, amount=1000,
                                             horizon_days=365, cdi=10, ipca=4)
    # CDB: 10% gross, IR 17.5% -> 8.25% net. LCI: 9% gross, tax exempt -> 9% net.
    # Tax-exempt LCI wins despite lower headline rate.
    assert cmp["best_id"] == str(lci.id)
    assert cmp["best_daily_id"] == str(lci.id)
    top = cmp["options"][0]
    assert top["name"] == "LCI Banco B"
    assert top["net_annual"] == 9.0
    assert top["net_earnings"] > 0


@pytest.mark.asyncio
async def test_fixed_income_api(client, auth_headers):
    r = await client.post("/api/fixed-income",
                          json={"name": "Tesouro Selic", "rate_kind": "cdi", "rate": 100,
                                "liquidity": "daily", "product_type": "Tesouro"},
                          headers=auth_headers)
    assert r.status_code == 201
    r = await client.get("/api/fixed-income", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()) == 1
    r = await client.get("/api/fixed-income/compare?amount=5000&horizon_days=720", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()["options"]) == 1
