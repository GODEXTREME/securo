"""add rollover flag to budgets (envelope budgeting)

Revision ID: 066
Revises: 065
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "066"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("budgets") as batch_op:
        # When true, the leftover/overspend of a category rolls into the next
        # month's available amount (YNAB/Actual-style envelope budgeting).
        batch_op.add_column(
            sa.Column("rollover", sa.Boolean(), nullable=False, server_default="false")
        )


def downgrade() -> None:
    with op.batch_alter_table("budgets") as batch_op:
        batch_op.drop_column("rollover")
