"""Propose-mutations.

These tools NEVER write to the DB. They return a structured proposal that
the agent surfaces to the user. The user confirms in the UI, which calls
the existing Securo write endpoint to do the real change. Keeps MCP safe
and gives the user a chance to review.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.group import Group, GroupMember
from app.models.recurring_transaction import RecurringTransaction
from app.models.transaction import Transaction
from mcp_server.auth import CallContext
from mcp_server.registry import tool
from mcp_server.tools._helpers import num, parse_date, parse_uuid, parse_uuid_list


# Repeated in EVERY propose_* tool description. The LLM reads these when
# deciding when to use a tool AND when describing the result to the user.
# The strong "REQUIRES USER CONFIRMATION" framing prevents the model from
# saying "Pronto! Criei…" / "Done! I added…" — the action is NOT executed
# by the tool call; it only takes effect when the user clicks Apply.
_PROPOSAL_PREFACE = (
    "[PROPOSAL — PREVIEW ONLY, NOT EXECUTED. The user MUST click Apply in "
    "the UI to confirm. Describe results as 'I prepared a proposal…' or "
    "'Here's a preview…' — NEVER as 'I created' / 'Done' / 'Ready'. The "
    "Apply button + diff card render automatically; do not duplicate the "
    "details in your reply.] "
)


@tool(
    name="propose_categorize",
    description=_PROPOSAL_PREFACE + (
        "Build a preview for re-categorizing one or more transactions. "
        "Returns a summary of what would change and the resolved category."
    ),
    parameters={
        "type": "object",
        "properties": {
            "transaction_ids": {"type": "array", "items": {"type": "string", "format": "uuid"}, "minItems": 1},
            "category_id": {"type": "string", "format": "uuid"},
        },
        "required": ["transaction_ids", "category_id"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "transactions"],
)
async def propose_categorize(
    *,
    session: AsyncSession,
    ctx: CallContext,
    transaction_ids: list[str],
    category_id: str,
) -> dict[str, Any]:
    cat_id = parse_uuid(category_id)
    cat = (await session.execute(
        select(Category).where(Category.id == cat_id, Category.user_id == ctx.user_id)
    )).scalar_one_or_none()
    if cat is None:
        return {"error": "category not found"}

    tx_ids = parse_uuid_list(transaction_ids) or []
    txs = (await session.execute(
        select(Transaction).where(Transaction.id.in_(tx_ids), Transaction.user_id == ctx.user_id)
    )).scalars().all()

    affected = [
        {"id": str(t.id), "description": t.description, "amount": num(t.amount), "currency": t.currency,
         "current_category_id": str(t.category_id) if t.category_id else None}
        for t in txs
    ]
    return {
        "kind": "categorize",
        "target_category": {"id": str(cat.id), "name": cat.name},
        "affected_count": len(affected),
        "affected": affected,
        "missing_ids": [str(t) for t in tx_ids if str(t) not in {a["id"] for a in affected}],
        "apply_endpoint": "POST /api/transactions/categorize",
    }


@tool(
    name="propose_create_category",
    description=_PROPOSAL_PREFACE + (
        "Preview the creation of a new category. Returns the proposed shape "
        "and any name collision detected."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 100},
            "group_id": {"type": "string", "format": "uuid"},
            "icon": {"type": "string"},
            "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "categories"],
)
async def propose_create_category(
    *,
    session: AsyncSession,
    ctx: CallContext,
    name: str,
    group_id: str | None = None,
    icon: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    existing = (await session.execute(
        select(Category.id, Category.name).where(
            Category.user_id == ctx.user_id,
            Category.name.ilike(name.strip()),
        )
    )).first()
    return {
        "kind": "create_category",
        "proposed": {
            "name": name.strip(),
            "group_id": str(parse_uuid(group_id)) if group_id else None,
            "icon": icon or "circle-help",
            "color": color or "#6B7280",
        },
        "name_collision": {"id": str(existing.id), "name": existing.name} if existing else None,
        "apply_endpoint": "POST /api/categories",
    }


@tool(
    name="propose_create_budget",
    description=_PROPOSAL_PREFACE + (
        "Preview a budget creation for a category and month. Returns the "
        "proposal plus any existing budget for the same category/month. "
        "STRICT: if the user mentions a category that does NOT match an "
        "existing one (call list_categories first to verify), do not "
        "silently substitute a different category — instead, ask the user "
        "to confirm an alternative or call propose_create_category first "
        "to add the missing one."
    ),
    parameters={
        "type": "object",
        "properties": {
            "category_id": {"type": "string", "format": "uuid"},
            "month": {"type": "string", "format": "date"},
            "amount": {"type": "number", "exclusiveMinimum": 0},
            "currency": {"type": "string"},
        },
        "required": ["category_id", "month", "amount"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "budgets"],
)
async def propose_create_budget(
    *,
    session: AsyncSession,
    ctx: CallContext,
    category_id: str,
    month: str,
    amount: float,
    currency: str | None = None,
) -> dict[str, Any]:
    cat_id = parse_uuid(category_id)
    target_month = (parse_date(month) or date.today()).replace(day=1)

    cat = (await session.execute(
        select(Category).where(Category.id == cat_id, Category.user_id == ctx.user_id)
    )).scalar_one_or_none()
    if cat is None:
        return {"error": "category not found"}

    return {
        "kind": "create_budget",
        "proposed": {
            "category_id": str(cat.id),
            "category_name": cat.name,
            "month": target_month.isoformat(),
            "amount": float(amount),
            "currency": currency,
        },
        "apply_endpoint": "POST /api/budgets",
    }


@tool(
    name="propose_create_transaction",
    description=_PROPOSAL_PREFACE + (
        "Build a preview for adding a one-off transaction (e.g. 'add a "
        "R$50 lunch today'). Validates the account/category exist; "
        "leaves currency to the account's default when not provided.\n\n"
        "Group splits: pass `group_id` + `splits` to attach a Splitwise-"
        "style breakdown. `splits.share_type='equal'` divides the amount "
        "evenly across the listed `member_ids` — perfect for 'crie no "
        "grupo dos Amigos e divida igualmente'. Use `'exact'` with a "
        "`share_amount` per member, or `'percent'` with `share_pct` per "
        "member, for custom shares. All members must belong to the same "
        "group as `group_id`. Call `list_groups` first to fetch IDs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "minLength": 1, "maxLength": 500},
            "amount": {"type": "number", "exclusiveMinimum": 0, "description": "Absolute value, always positive — direction comes from `type`"},
            "type": {"type": "string", "enum": ["debit", "credit"], "description": "debit = expense, credit = income"},
            "account_id": {"type": "string", "format": "uuid"},
            "category_id": {"type": "string", "format": "uuid"},
            "date": {"type": "string", "format": "date", "description": "Defaults to today"},
            "currency": {"type": "string", "description": "Defaults to the account's currency"},
            "notes": {"type": "string"},
            "group_id": {"type": "string", "format": "uuid", "description": "Optional: attach to an expense-sharing group"},
            "splits": {
                "type": "object",
                "description": "Required when `group_id` is set. Defines how the amount is split among group members.",
                "properties": {
                    "share_type": {"type": "string", "enum": ["equal", "exact", "percent"]},
                    "members": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "member_id": {"type": "string", "format": "uuid"},
                                "share_amount": {"type": "number", "description": "Required for share_type='exact' (sum must equal `amount`)"},
                                "share_pct": {"type": "number", "description": "Required for share_type='percent' (must sum to 100)"},
                            },
                            "required": ["member_id"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["share_type", "members"],
                "additionalProperties": False,
            },
        },
        "required": ["description", "amount", "type", "account_id"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "transactions"],
)
async def propose_create_transaction(
    *,
    session: AsyncSession,
    ctx: CallContext,
    description: str,
    amount: float,
    type: str,
    account_id: str,
    category_id: str | None = None,
    date: str | None = None,
    currency: str | None = None,
    notes: str | None = None,
    group_id: str | None = None,
    splits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    acc_id = parse_uuid(account_id)
    acc = (await session.execute(
        select(Account).where(Account.id == acc_id, Account.user_id == ctx.user_id)
    )).scalar_one_or_none()
    if acc is None:
        return {"error": "account not found"}

    cat = None
    if category_id:
        cat = (await session.execute(
            select(Category).where(Category.id == parse_uuid(category_id), Category.user_id == ctx.user_id)
        )).scalar_one_or_none()
        if cat is None:
            return {"error": "category not found"}

    # Validate group + splits (if any) so the preview is honest.
    splits_preview: list[dict[str, Any]] | None = None
    group_name: str | None = None
    if group_id or splits:
        if not (group_id and splits):
            return {"error": "group_id and splits must be provided together"}
        gid = parse_uuid(group_id)
        group = (await session.execute(
            select(Group).where(Group.id == gid, Group.user_id == ctx.user_id)
        )).scalar_one_or_none()
        if group is None:
            return {"error": "group not found"}
        group_name = group.name

        share_type = splits.get("share_type")
        if share_type not in ("equal", "exact", "percent"):
            return {"error": f"invalid share_type: {share_type!r}"}
        members_in = splits.get("members") or []
        if not members_in:
            return {"error": "splits.members must not be empty"}
        member_ids = [parse_uuid(m["member_id"]) for m in members_in]
        rows = (await session.execute(
            select(GroupMember).where(GroupMember.id.in_(member_ids), GroupMember.group_id == gid)
        )).scalars().all()
        if len(rows) != len(set(member_ids)):
            return {"error": "one or more members do not belong to the given group"}
        name_by_id = {m.id: m.name for m in rows}

        # Materialize a preview for the UI/LLM. The actual write happens
        # via POST /api/transactions which re-runs the same math.
        n = len(members_in)
        amt = float(amount)
        if share_type == "equal":
            per = round(amt / n, 2)
            residual = round(amt - per * (n - 1), 2)
            splits_preview = [
                {
                    "member_id": str(m["member_id"]),
                    "member_name": name_by_id.get(parse_uuid(m["member_id"]), "?"),
                    "share_amount": (residual if i == n - 1 else per),
                }
                for i, m in enumerate(members_in)
            ]
        elif share_type == "exact":
            total = round(sum((float(m.get("share_amount") or 0) for m in members_in), 0.0), 2)
            if abs(total - amt) > 0.01:
                return {"error": f"exact share amounts sum to {total}, expected {amt}"}
            splits_preview = [
                {
                    "member_id": str(m["member_id"]),
                    "member_name": name_by_id.get(parse_uuid(m["member_id"]), "?"),
                    "share_amount": float(m.get("share_amount") or 0),
                }
                for m in members_in
            ]
        else:  # percent
            pct_sum = round(sum((float(m.get("share_pct") or 0) for m in members_in), 0.0), 2)
            if abs(pct_sum - 100.0) > 0.01:
                return {"error": f"percent shares sum to {pct_sum}, expected 100"}
            running = 0.0
            splits_preview = []
            for i, m in enumerate(members_in):
                if i == n - 1:
                    share = round(amt - running, 2)
                else:
                    share = round(amt * float(m.get("share_pct") or 0) / 100.0, 2)
                    running += share
                splits_preview.append({
                    "member_id": str(m["member_id"]),
                    "member_name": name_by_id.get(parse_uuid(m["member_id"]), "?"),
                    "share_amount": share,
                    "share_pct": float(m.get("share_pct") or 0),
                })

    target_date = parse_date(date) or _today()
    proposed: dict[str, Any] = {
        "description": description.strip(),
        "amount": float(amount),
        "currency": (currency or acc.currency or "USD").upper(),
        "type": type,
        "date": target_date.isoformat(),
        "account_id": str(acc.id),
        "account_name": acc.name,
        "category_id": str(cat.id) if cat else None,
        "category_name": cat.name if cat else None,
        "notes": (notes or None),
    }
    if splits_preview is not None:
        proposed["group_id"] = group_id
        proposed["group_name"] = group_name
        proposed["splits"] = {
            "share_type": splits["share_type"],
            "items": splits_preview,
        }
    return {
        "kind": "create_transaction",
        "proposed": proposed,
        "apply_endpoint": "POST /api/transactions",
    }


@tool(
    name="propose_create_recurring_transaction",
    description=_PROPOSAL_PREFACE + (
        "Build a preview for adding a recurring transaction / subscription "
        "(e.g. 'Netflix R$55 every month on the 10th'). Frequency is one "
        "of weekly/monthly/yearly. For monthly use day_of_month (1-31)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "minLength": 1, "maxLength": 500},
            "amount": {"type": "number", "exclusiveMinimum": 0},
            "type": {"type": "string", "enum": ["debit", "credit"]},
            "frequency": {"type": "string", "enum": ["weekly", "monthly", "yearly"]},
            "day_of_month": {"type": "integer", "minimum": 1, "maximum": 31, "description": "Required for monthly"},
            "start_date": {"type": "string", "format": "date", "description": "Defaults to today"},
            "end_date": {"type": "string", "format": "date"},
            "account_id": {"type": "string", "format": "uuid"},
            "category_id": {"type": "string", "format": "uuid"},
            "currency": {"type": "string"},
        },
        "required": ["description", "amount", "type", "frequency", "account_id"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "recurring"],
)
async def propose_create_recurring_transaction(
    *,
    session: AsyncSession,
    ctx: CallContext,
    description: str,
    amount: float,
    type: str,
    frequency: str,
    account_id: str,
    day_of_month: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    category_id: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    if frequency == "monthly" and not day_of_month:
        return {"error": "day_of_month is required for monthly frequency"}
    acc = (await session.execute(
        select(Account).where(Account.id == parse_uuid(account_id), Account.user_id == ctx.user_id)
    )).scalar_one_or_none()
    if acc is None:
        return {"error": "account not found"}
    cat = None
    if category_id:
        cat = (await session.execute(
            select(Category).where(Category.id == parse_uuid(category_id), Category.user_id == ctx.user_id)
        )).scalar_one_or_none()
        if cat is None:
            return {"error": "category not found"}

    return {
        "kind": "create_recurring_transaction",
        "proposed": {
            "description": description.strip(),
            "amount": float(amount),
            "currency": (currency or acc.currency or "USD").upper(),
            "type": type,
            "frequency": frequency,
            "day_of_month": int(day_of_month) if day_of_month else None,
            "start_date": (parse_date(start_date) or _today()).isoformat(),
            "end_date": parse_date(end_date).isoformat() if end_date else None,
            "account_id": str(acc.id),
            "account_name": acc.name,
            "category_id": str(cat.id) if cat else None,
            "category_name": cat.name if cat else None,
        },
        "apply_endpoint": "POST /api/recurring-transactions",
    }


@tool(
    name="propose_update_recurring_transaction",
    description=_PROPOSAL_PREFACE + (
        "Build a preview for editing an existing recurring transaction "
        "(e.g. 'update my salary to R$8,000', 'change Netflix to R$60'). "
        "Pass the recurring_id and only the fields you want to change. "
        "Returns the current values alongside the proposed changes so the "
        "user can compare before confirming."
    ),
    parameters={
        "type": "object",
        "properties": {
            "recurring_id": {"type": "string", "format": "uuid"},
            "description": {"type": "string", "minLength": 1, "maxLength": 500},
            "amount": {"type": "number", "exclusiveMinimum": 0},
            "frequency": {"type": "string", "enum": ["weekly", "monthly", "yearly"]},
            "day_of_month": {"type": "integer", "minimum": 1, "maximum": 31},
            "end_date": {"type": "string", "format": "date"},
            "category_id": {"type": "string", "format": "uuid"},
            "is_active": {"type": "boolean"},
        },
        "required": ["recurring_id"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "recurring"],
)
async def propose_update_recurring_transaction(
    *,
    session: AsyncSession,
    ctx: CallContext,
    recurring_id: str,
    description: str | None = None,
    amount: float | None = None,
    frequency: str | None = None,
    day_of_month: int | None = None,
    end_date: str | None = None,
    category_id: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    rid = parse_uuid(recurring_id)
    rt = (await session.execute(
        select(RecurringTransaction).where(
            RecurringTransaction.id == rid, RecurringTransaction.user_id == ctx.user_id
        )
    )).scalar_one_or_none()
    if rt is None:
        return {"error": "recurring transaction not found"}

    cat = None
    if category_id:
        cat = (await session.execute(
            select(Category).where(Category.id == parse_uuid(category_id), Category.user_id == ctx.user_id)
        )).scalar_one_or_none()
        if cat is None:
            return {"error": "category not found"}

    changes: dict[str, Any] = {}
    if description is not None:
        changes["description"] = description.strip()
    if amount is not None:
        changes["amount"] = float(amount)
    if frequency is not None:
        changes["frequency"] = frequency
    if day_of_month is not None:
        changes["day_of_month"] = int(day_of_month)
    if end_date is not None:
        changes["end_date"] = parse_date(end_date).isoformat() if end_date else None
    if cat is not None:
        changes["category_id"] = str(cat.id)
    if is_active is not None:
        changes["is_active"] = bool(is_active)

    if not changes:
        return {"error": "no changes provided"}

    return {
        "kind": "update_recurring_transaction",
        "target": {
            "id": str(rt.id),
            "description": rt.description,
            "amount": num(rt.amount),
            "currency": rt.currency,
            "frequency": rt.frequency,
            "day_of_month": rt.day_of_month,
            "is_active": bool(getattr(rt, "is_active", True)),
        },
        "changes": changes,
        "apply_endpoint": f"PATCH /api/recurring-transactions/{rt.id}",
    }


@tool(
    name="propose_cancel_recurring_transaction",
    description=_PROPOSAL_PREFACE + (
        "Build a preview for cancelling a recurring transaction (e.g. "
        "'cancel that subscription'). Two modes: 'deactivate' keeps the "
        "history but stops future occurrences (recommended); 'delete' "
        "removes it entirely."
    ),
    parameters={
        "type": "object",
        "properties": {
            "recurring_id": {"type": "string", "format": "uuid"},
            "mode": {"type": "string", "enum": ["deactivate", "delete"], "default": "deactivate"},
        },
        "required": ["recurring_id"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "recurring"],
)
async def propose_cancel_recurring_transaction(
    *,
    session: AsyncSession,
    ctx: CallContext,
    recurring_id: str,
    mode: str = "deactivate",
) -> dict[str, Any]:
    rt = (await session.execute(
        select(RecurringTransaction).where(
            RecurringTransaction.id == parse_uuid(recurring_id),
            RecurringTransaction.user_id == ctx.user_id,
        )
    )).scalar_one_or_none()
    if rt is None:
        return {"error": "recurring transaction not found"}

    if mode == "delete":
        endpoint = f"DELETE /api/recurring-transactions/{rt.id}"
    else:
        endpoint = f"PATCH /api/recurring-transactions/{rt.id}  body={{is_active: false}}"

    return {
        "kind": "cancel_recurring_transaction",
        "mode": mode,
        "target": {
            "id": str(rt.id),
            "description": rt.description,
            "amount": num(rt.amount),
            "currency": rt.currency,
            "frequency": rt.frequency,
            "is_active": bool(getattr(rt, "is_active", True)),
        },
        "apply_endpoint": endpoint,
    }


@tool(
    name="propose_create_goal",
    description=_PROPOSAL_PREFACE + (
        "Build a preview for creating a savings/financial goal (e.g. "
        "'set a R$10k goal for travel')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 255},
            "target_amount": {"type": "number", "exclusiveMinimum": 0},
            "currency": {"type": "string", "description": "Defaults to user's primary currency"},
            "deadline": {"type": "string", "format": "date"},
            "initial_amount": {"type": "number", "minimum": 0, "description": "How much you've already saved"},
            "icon": {"type": "string"},
            "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        },
        "required": ["name", "target_amount"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "goals"],
)
async def propose_create_goal(
    *,
    session: AsyncSession,
    ctx: CallContext,
    name: str,
    target_amount: float,
    currency: str | None = None,
    deadline: str | None = None,
    initial_amount: float | None = None,
    icon: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "create_goal",
        "proposed": {
            "name": name.strip(),
            "target_amount": float(target_amount),
            "currency": (currency or "BRL").upper(),
            "deadline": parse_date(deadline).isoformat() if deadline else None,
            "initial_amount": float(initial_amount) if initial_amount is not None else 0.0,
            "icon": icon or "target",
            "color": color or "#3B82F6",
        },
        "apply_endpoint": "POST /api/goals",
    }


def _today():
    from datetime import date as _d
    return _d.today()


@tool(
    name="propose_create_payee_rule",
    description=_PROPOSAL_PREFACE + (
        "Preview a rule that auto-categorizes future transactions matching "
        "a description pattern. Returns the proposed rule shape."
    ),
    parameters={
        "type": "object",
        "properties": {
            "match_pattern": {"type": "string", "description": "Substring to match in transaction description (case-insensitive)"},
            "category_id": {"type": "string", "format": "uuid"},
        },
        "required": ["match_pattern", "category_id"],
        "additionalProperties": False,
    },
    is_proposal=True,
    tags=["propose", "rules"],
)
async def propose_create_payee_rule(
    *,
    session: AsyncSession,
    ctx: CallContext,
    match_pattern: str,
    category_id: str,
) -> dict[str, Any]:
    cat_id = parse_uuid(category_id)
    cat = (await session.execute(
        select(Category).where(Category.id == cat_id, Category.user_id == ctx.user_id)
    )).scalar_one_or_none()
    if cat is None:
        return {"error": "category not found"}

    return {
        "kind": "create_payee_rule",
        "proposed": {
            "match_pattern": match_pattern,
            "category_id": str(cat.id),
            "category_name": cat.name,
        },
        "apply_endpoint": "POST /api/rules",
    }
