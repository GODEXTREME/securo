"""Group credit-card installment purchases.

Bank-synced installments ("3/12", "4/12", …) arrive as separate transactions
that share installment metadata. This groups them back into the original
purchase so the user can see one line per purchase and categorize the whole
plan at once (via the existing bulk-categorize endpoint) instead of tagging
each parcel. Pure read — returns the member transaction ids per plan.
"""
import re
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction


def _normalize(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"\b\d+\s*/\s*\d+\b", "", t)  # strip "3/12" markers
    t = re.sub(r"\d+", "", t)
    t = re.sub(r"[^a-zà-ÿ ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:60]


def _plan_key(tx: Transaction) -> str:
    if tx.installment_purchase_date and tx.installment_total_amount:
        return (
            f"{tx.account_id}|{tx.installment_purchase_date.isoformat()}"
            f"|{tx.total_installments}|{round(float(tx.installment_total_amount), 2)}"
        )
    return f"{tx.account_id}|{_normalize(tx.description)}|{tx.total_installments}"


async def group_plans(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    only_uncategorized: bool = False,
    account_id: uuid.UUID | None = None,
    lookback_days: int = 730,
) -> dict:
    since = date.today() - timedelta(days=lookback_days)
    stmt = select(Transaction).where(
        Transaction.workspace_id == workspace_id,
        Transaction.total_installments.isnot(None),
        Transaction.total_installments > 1,
        Transaction.date >= since,
    )
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    txns = list((await session.execute(stmt)).scalars().all())

    # Names for accounts and categories referenced.
    account_ids = {t.account_id for t in txns}
    cat_ids = {t.category_id for t in txns if t.category_id}
    acc_names: dict[uuid.UUID, str] = {}
    if account_ids:
        rows = await session.execute(
            select(Account.id, Account.name, Account.display_name).where(Account.id.in_(account_ids))
        )
        acc_names = {r[0]: (r[2] or r[1]) for r in rows.all()}
    cat_map: dict[uuid.UUID, tuple[str, str]] = {}
    if cat_ids:
        rows = await session.execute(
            select(Category.id, Category.name, Category.color).where(Category.id.in_(cat_ids))
        )
        cat_map = {r[0]: (r[1], r[2]) for r in rows.all()}

    groups: dict[str, list[Transaction]] = {}
    for tx in txns:
        groups.setdefault(_plan_key(tx), []).append(tx)

    plans = []
    for key, items in groups.items():
        items.sort(key=lambda t: (t.installment_number or 0, t.date))
        first = items[0]
        cats = {t.category_id for t in items}
        uncategorized = None in cats or len(cats) > 1 or first.category_id is None
        if only_uncategorized and not uncategorized:
            continue

        total = (
            float(first.installment_total_amount)
            if first.installment_total_amount is not None
            else round(sum(abs(float(t.amount)) for t in items), 2)
        )
        cat_id = first.category_id if len(cats) == 1 else None
        cat_name, cat_color = cat_map.get(cat_id, (None, None)) if cat_id else (None, None)

        plans.append({
            "key": key,
            "name": first.payee or first.description[:80],
            "account_id": str(first.account_id),
            "account_name": acc_names.get(first.account_id, ""),
            "total_installments": first.total_installments,
            "paid_count": len(items),
            "per_installment": round(abs(float(first.amount)), 2),
            "total_amount": round(total, 2),
            "currency": first.currency,
            "purchase_date": (
                first.installment_purchase_date.isoformat()
                if first.installment_purchase_date else first.date.isoformat()
            ),
            "category_id": str(cat_id) if cat_id else None,
            "category_name": cat_name,
            "category_color": cat_color,
            "mixed_categories": len(cats) > 1,
            "uncategorized": bool(uncategorized),
            "transaction_ids": [str(t.id) for t in items],
        })

    plans.sort(key=lambda p: (not p["uncategorized"], p["purchase_date"]), reverse=False)
    return {
        "count": len(plans),
        "uncategorized_count": sum(1 for p in plans if p["uncategorized"]),
        "plans": plans,
    }
