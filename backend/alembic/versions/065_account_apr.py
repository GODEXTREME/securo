"""add apr to accounts for debt payoff planning

Revision ID: 065
Revises: 064
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "065"
down_revision: Union[str, None] = "064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        # Annual percentage rate (e.g. 24.90 for 24.9%). Used by the debt
        # payoff planner; null when unknown.
        batch_op.add_column(sa.Column("apr", sa.Numeric(precision=6, scale=3), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("apr")
