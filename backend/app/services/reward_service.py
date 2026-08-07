"""Cashback / rewards tracking.

Users register per-card reward rules ("this card gives X% back on category Y",
or a card-wide default rate). The summary matches the workspace's spending to
the most specific rule for each transaction and reports how much cashback was
earned, broken down by card and by category, plus which card is the best choice
for each category.
"""
import uuid
from calendar import monthrange as _monthrange
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.reward_rule import RewardRule
from app.models.transaction import Transaction
from app.schemas.reward import RewardRuleCreate, RewardRuleRead, RewardRuleUpdate
from app.services.account_service import get_account_name


async def _to_read(session: AsyncSession, rule: RewardRule) -> RewardRuleRead:
    read = RewardRuleRead.model_validate(rule)
    acc = await session.get(Account, rule.account_id)
    if acc:
        read.account_name = get_account_name(acc)
    if rule.category_id:
        cat = await session.get(Category, rule.category_id)
        if cat:
            read.category_name = cat.name
            read.category_color = cat.color
    return read


async def list_rules(session: AsyncSession, workspace_id: uuid.UUID) -> list[RewardRuleRead]:
    stmt = select(RewardRule).where(RewardRule.workspace_id == workspace_id).order_by(RewardRule.created_at)
    rules = list((await session.execute(stmt)).scalars().all())
    return [await _to_read(session, r) for r in rules]


async def get_rule(session: AsyncSession, rule_id: uuid.UUID, workspace_id: uuid.UUID) -> Optional[RewardRule]:
    rule = await session.get(RewardRule, rule_id)
    if not rule or rule.workspace_id != workspace_id:
        return None
    return rule


async def create_rule(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, data: RewardRuleCreate
) -> RewardRuleRead:
    rule = RewardRule(
        user_id=user_id,
        workspace_id=workspace_id,
        account_id=data.account_id,
        category_id=data.category_id,
        rate=data.rate,
        name=data.name,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return await _to_read(session, rule)


async def update_rule(
    session: AsyncSession, rule_id: uuid.UUID, workspace_id: uuid.UUID, data: RewardRuleUpdate
) -> Optional[RewardRuleRead]:
    rule = await get_rule(session, rule_id, workspace_id)
    if not rule:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    await session.commit()
    await session.refresh(rule)
    return await _to_read(session, rule)


async def delete_rule(session: AsyncSession, rule_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
    rule = await get_rule(session, rule_id, workspace_id)
    if not rule:
        return False
    await session.delete(rule)
    await session.commit()
    return True


async def summary(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    year: Optional[int] = None,
    month: Optional[int] = None,
    months: int = 1,
) -> dict:
    from app.services.advanced_report_service import _currency, _range_start

    currency = await _currency(session, user_id)

    if year and month:
        start = date(year, month, 1)
        end = date(year, month, _monthrange(year, month)[1])
    else:
        start = _range_start(months, None)
        end = date.today()

    # rules: account_id -> {category_id or None: (rate, rule)}
    rules = list((await session.execute(
        select(RewardRule).where(RewardRule.workspace_id == workspace_id)
    )).scalars().all())
    rate_map: dict[uuid.UUID, dict[Optional[uuid.UUID], float]] = defaultdict(dict)
    for r in rules:
        rate_map[r.account_id][r.category_id] = float(r.rate)

    amount = func.coalesce(Transaction.amount_primary, Transaction.amount)
    rows = await session.execute(
        select(Transaction.account_id, Transaction.category_id, func.sum(func.abs(amount)))
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.is_ignored == False,
            Transaction.date >= start,
            Transaction.date <= end,
        )
        .group_by(Transaction.account_id, Transaction.category_id)
    )

    by_card: dict[uuid.UUID, dict] = {}
    by_category: dict[Optional[uuid.UUID], dict] = {}
    total_earned = 0.0
    total_spend = 0.0

    for account_id, category_id, spend in rows.all():
        spend = float(spend or 0)
        acc_rates = rate_map.get(account_id)
        if not acc_rates:
            continue
        rate = acc_rates.get(category_id)
        if rate is None:
            rate = acc_rates.get(None)  # card default
        if rate is None:
            continue
        earned = spend * rate / 100.0
        total_earned += earned
        total_spend += spend
        card = by_card.setdefault(account_id, {"account_id": str(account_id), "earned": 0.0, "spend": 0.0})
        card["earned"] += earned
        card["spend"] += spend
        cat = by_category.setdefault(category_id, {"category_id": str(category_id) if category_id else None, "earned": 0.0, "spend": 0.0})
        cat["earned"] += earned
        cat["spend"] += spend

    # Resolve names.
    for account_id, card in by_card.items():
        acc = await session.get(Account, account_id)
        card["name"] = get_account_name(acc) if acc else "?"
        card["earned"] = round(card["earned"], 2)
        card["spend"] = round(card["spend"], 2)
    for category_id, cat in by_category.items():
        if category_id:
            c = await session.get(Category, category_id)
            cat["name"] = c.name if c else "?"
            cat["color"] = c.color if c else None
        else:
            cat["name"] = None
            cat["color"] = None
        cat["earned"] = round(cat["earned"], 2)
        cat["spend"] = round(cat["spend"], 2)

    # Best card per category across all rules (highest rate wins).
    best: dict[Optional[uuid.UUID], tuple[uuid.UUID, float]] = {}
    for account_id, cats in rate_map.items():
        for category_id, rate in cats.items():
            cur = best.get(category_id)
            if cur is None or rate > cur[1]:
                best[category_id] = (account_id, rate)
    best_per_category: list[dict[str, Any]] = []
    for category_id, (account_id, rate) in best.items():
        acc = await session.get(Account, account_id)
        if category_id:
            c = await session.get(Category, category_id)
            cat_name = c.name if c else "?"
            cat_color = c.color if c else None
        else:
            cat_name = None
            cat_color = None
        best_per_category.append({
            "category_id": str(category_id) if category_id else None,
            "category_name": cat_name,
            "category_color": cat_color,
            "account_name": get_account_name(acc) if acc else "?",
            "rate": rate,
        })
    best_per_category.sort(key=lambda x: x["rate"], reverse=True)

    return {
        "currency": currency,
        "total_earned": round(total_earned, 2),
        "total_spend": round(total_spend, 2),
        "effective_rate": round(total_earned / total_spend * 100, 2) if total_spend > 0 else 0.0,
        "by_card": sorted(by_card.values(), key=lambda c: c["earned"], reverse=True),
        "by_category": sorted(by_category.values(), key=lambda c: c["earned"], reverse=True),
        "best_per_category": best_per_category,
    }
