"""add provider next_close_date / next_due_date to accounts

Revision ID: 075
Revises: 074
Create Date: 2026-07-19

The provider (Pluggy) reports the credit card's actual next close/due DATES
(balanceCloseDate / balanceDueDate), which reflect the bank shifting the cycle
for weekends/holidays. We previously kept only the day-of-month; store the full
dates so a purchase in the still-open cycle buckets into the right fatura before
its bill link arrives.

Additive and nullable: existing rows are unaffected and backfill on the next
sync.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "075"
down_revision: Union[str, None] = "074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("next_close_date", sa.Date(), nullable=True))
    op.add_column("accounts", sa.Column("next_due_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "next_due_date")
    op.drop_column("accounts", "next_close_date")
