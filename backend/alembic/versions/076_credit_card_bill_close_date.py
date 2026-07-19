"""add close_date to credit_card_bills

Revision ID: 076
Revises: 075
Create Date: 2026-07-19

Pluggy's /bills payload carries only the due date, not the statement close
date. We snapshot the account's real next_close_date onto the matching bill at
sync time (exact) and derive it from the close day for the rest, so the fatura
chart can be clamped to the true cycle boundary instead of the nominal day.

Additive and nullable: existing rows are unaffected and backfill on the next
sync.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "076"
down_revision: Union[str, None] = "075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("credit_card_bills", sa.Column("close_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("credit_card_bills", "close_date")
