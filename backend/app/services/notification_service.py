"""In-app notifications / alerts.

`generate_for_workspace` inspects the workspace's current financial state and
creates notifications for a handful of triggers (budget overspend, upcoming
credit-card bills, overdrawn/low balances, unusually large transactions). It is
idempotent within a period thanks to per-alert ``dedup_key``s, so it is safe to
run on a schedule (Celery beat) and on demand (the frontend calls
``POST /api/notifications/refresh`` on load).

Optionally mirrors warning/critical alerts to an outgoing webhook and/or a
Telegram chat when configured in admin settings — best-effort, never blocks.
"""
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.credit_card_bill import CreditCardBill
from app.models.notification import Notification
from app.models.transaction import Transaction
from app.services import admin_service, budget_service, dashboard_service

logger = logging.getLogger(__name__)

# How many days ahead an upcoming credit-card bill triggers a reminder.
BILL_DUE_WINDOW_DAYS = 5
# Transactions in the last N days are considered for the "large transaction" alert.
LARGE_TXN_LOOKBACK_DAYS = 3


async def _setting(session: AsyncSession, key: str, default: str) -> str:
    row = await admin_service.get_app_setting(session, key)
    return row.value if row and row.value else default


async def _dedup_exists(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, dedup_key: str
) -> bool:
    existing = await session.scalar(
        select(Notification.id).where(
            Notification.workspace_id == workspace_id,
            Notification.user_id == user_id,
            Notification.dedup_key == dedup_key,
        )
    )
    return existing is not None


async def create_notification(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    type: str,
    title: str,
    body: Optional[str] = None,
    severity: str = "info",
    link: Optional[str] = None,
    dedup_key: Optional[str] = None,
    data_json: Optional[Any] = None,
    deliver: bool = True,
) -> Optional[Notification]:
    """Create a notification, skipping if an identical ``dedup_key`` exists."""
    if dedup_key and await _dedup_exists(session, workspace_id, user_id, dedup_key):
        return None
    notif = Notification(
        user_id=user_id,
        workspace_id=workspace_id,
        type=type,
        severity=severity,
        title=title,
        body=body,
        link=link,
        dedup_key=dedup_key,
        data_json=data_json,
    )
    session.add(notif)
    await session.flush()
    if deliver and severity in ("warning", "critical"):
        await _deliver_external(session, notif)
    return notif


async def _deliver_external(session: AsyncSession, notif: Notification) -> None:
    """Best-effort mirror to a webhook and/or Telegram chat. Never raises."""
    try:
        webhook = await _setting(session, "notify_webhook_url", "")
        tg_token = await _setting(session, "notify_telegram_bot_token", "")
        tg_chat = await _setting(session, "notify_telegram_chat_id", "")
        if not webhook and not (tg_token and tg_chat):
            return
        text = f"[{notif.severity.upper()}] {notif.title}"
        if notif.body:
            text += f"\n{notif.body}"
        async with httpx.AsyncClient(timeout=10) as client:
            if webhook:
                await client.post(webhook, json={
                    "type": notif.type,
                    "severity": notif.severity,
                    "title": notif.title,
                    "body": notif.body,
                    "link": notif.link,
                })
            if tg_token and tg_chat:
                await client.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": tg_chat, "text": text},
                )
    except Exception:
        logger.warning("notification external delivery failed", exc_info=True)


# --------------------------------------------------------------------------
# Trigger generation
# --------------------------------------------------------------------------

async def _check_budgets(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    month = date.today().replace(day=1)
    tag = month.strftime("%Y-%m")
    rows = await budget_service.get_budget_vs_actual(session, workspace_id, user_id, month)
    for r in rows:
        if r.budget_amount is None or r.budget_amount <= 0:
            continue
        pct = r.percentage_used or 0.0
        if pct >= 100:
            await create_notification(
                session, workspace_id, user_id,
                type="budget_exceeded", severity="warning",
                title=f"Budget exceeded: {r.category_name}",
                body=f"You've spent {pct:.0f}% of your {r.category_name} budget this month.",
                link="/budgets",
                dedup_key=f"budget_exceeded:{r.category_id}:{tag}",
                data_json={"category_id": str(r.category_id), "percentage": pct},
            )
        elif pct >= 90:
            await create_notification(
                session, workspace_id, user_id,
                type="budget_exceeded", severity="info",
                title=f"Budget almost used: {r.category_name}",
                body=f"You've used {pct:.0f}% of your {r.category_name} budget this month.",
                link="/budgets",
                dedup_key=f"budget_near:{r.category_id}:{tag}",
                data_json={"category_id": str(r.category_id), "percentage": pct},
            )


async def _check_bills(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    today = date.today()
    horizon = today + timedelta(days=BILL_DUE_WINDOW_DAYS)
    result = await session.execute(
        select(CreditCardBill, Account.name)
        .join(Account, CreditCardBill.account_id == Account.id)
        .where(
            CreditCardBill.workspace_id == workspace_id,
            CreditCardBill.due_date >= today,
            CreditCardBill.due_date <= horizon,
        )
    )
    for bill, account_name in result.all():
        days = (bill.due_date - today).days
        when = "today" if days == 0 else f"in {days} day(s)"
        await create_notification(
            session, workspace_id, user_id,
            type="bill_due", severity="warning" if days <= 2 else "info",
            title=f"Bill due {when}: {account_name}",
            body=f"{account_name} statement of {bill.total_amount} {bill.currency} is due on {bill.due_date.isoformat()}.",
            link="/accounts",
            dedup_key=f"bill_due:{bill.id}",
            data_json={"account_id": str(bill.account_id), "due_date": bill.due_date.isoformat()},
        )


async def _check_low_balance(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    threshold = Decimal(await _setting(session, "low_balance_threshold", "0"))
    tag = date.today().strftime("%Y-%m-%d")
    accounts = await dashboard_service._get_open_accounts(session, workspace_id)
    for acc in accounts:
        if acc.type in ("credit_card", "investment"):
            continue
        bal = acc.balance if acc.balance is not None else Decimal("0")
        if bal < 0:
            await create_notification(
                session, workspace_id, user_id,
                type="low_balance", severity="critical",
                title=f"Account overdrawn: {acc.display_name or acc.name}",
                body=f"Balance is {bal} {acc.currency}.",
                link=f"/accounts/{acc.id}",
                dedup_key=f"overdrawn:{acc.id}:{tag}",
                data_json={"account_id": str(acc.id), "balance": float(bal)},
            )
        elif threshold > 0 and bal < threshold:
            await create_notification(
                session, workspace_id, user_id,
                type="low_balance", severity="warning",
                title=f"Low balance: {acc.display_name or acc.name}",
                body=f"Balance is {bal} {acc.currency}, below your {threshold} threshold.",
                link=f"/accounts/{acc.id}",
                dedup_key=f"low_balance:{acc.id}:{tag}",
                data_json={"account_id": str(acc.id), "balance": float(bal)},
            )


async def _check_large_transactions(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    configured = Decimal(await _setting(session, "large_transaction_threshold", "0"))
    since = date.today() - timedelta(days=LARGE_TXN_LOOKBACK_DAYS)

    threshold = configured
    if threshold <= 0:
        # Dynamic threshold: 4x the average expense over the last 90 days.
        avg = await session.scalar(
            select(func.avg(func.abs(func.coalesce(Transaction.amount_primary, Transaction.amount)))).where(
                Transaction.workspace_id == workspace_id,
                Transaction.type == "debit",
                Transaction.date >= date.today() - timedelta(days=90),
                Transaction.is_ignored == False,
            )
        )
        threshold = (Decimal(str(avg)) * 4) if avg else Decimal("1000")

    result = await session.execute(
        select(Transaction).where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.date >= since,
            Transaction.is_ignored == False,
            func.abs(func.coalesce(Transaction.amount_primary, Transaction.amount)) >= threshold,
        )
    )
    for tx in result.scalars().all():
        amt = abs(tx.amount)
        await create_notification(
            session, workspace_id, user_id,
            type="large_transaction", severity="info",
            title=f"Large transaction: {tx.description[:60]}",
            body=f"{amt} {tx.currency} on {tx.date.isoformat()}.",
            link="/transactions",
            dedup_key=f"large_txn:{tx.id}",
            data_json={"transaction_id": str(tx.id), "amount": float(amt)},
        )


async def generate_for_workspace(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    """Run all trigger checks. Returns the number of new notifications created."""
    before = await session.scalar(
        select(func.count(Notification.id)).where(
            Notification.workspace_id == workspace_id, Notification.user_id == user_id
        )
    ) or 0
    for check in (_check_budgets, _check_bills, _check_low_balance, _check_large_transactions):
        try:
            await check(session, workspace_id, user_id)
        except Exception:
            logger.warning("notification check %s failed", check.__name__, exc_info=True)
    await session.commit()
    after = await session.scalar(
        select(func.count(Notification.id)).where(
            Notification.workspace_id == workspace_id, Notification.user_id == user_id
        )
    ) or 0
    return max(0, after - before)


# --------------------------------------------------------------------------
# Read / mutate
# --------------------------------------------------------------------------

async def list_notifications(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID,
    unread_only: bool = False, limit: int = 50,
) -> tuple[list[Notification], int]:
    stmt = select(Notification).where(
        Notification.workspace_id == workspace_id,
        Notification.user_id == user_id,
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    items = list((await session.execute(stmt)).scalars().all())
    unread = await unread_count(session, workspace_id, user_id)
    return items, unread


async def unread_count(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    return await session.scalar(
        select(func.count(Notification.id)).where(
            Notification.workspace_id == workspace_id,
            Notification.user_id == user_id,
            Notification.is_read == False,
        )
    ) or 0


async def mark_read(
    session: AsyncSession, notif_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    result = await session.execute(
        update(Notification)
        .where(
            Notification.id == notif_id,
            Notification.workspace_id == workspace_id,
            Notification.user_id == user_id,
        )
        .values(is_read=True)
    )
    await session.commit()
    return result.rowcount > 0


async def mark_all_read(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    result = await session.execute(
        update(Notification)
        .where(
            Notification.workspace_id == workspace_id,
            Notification.user_id == user_id,
            Notification.is_read == False,
        )
        .values(is_read=True)
    )
    await session.commit()
    return result.rowcount


async def delete_notification(
    session: AsyncSession, notif_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    notif = await session.get(Notification, notif_id)
    if not notif or notif.workspace_id != workspace_id or notif.user_id != user_id:
        return False
    await session.delete(notif)
    await session.commit()
    return True
