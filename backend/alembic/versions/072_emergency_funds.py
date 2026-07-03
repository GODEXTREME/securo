"""emergency funds (reserva de emergência)

Revision ID: 072
Revises: 071
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "072"
down_revision: Union[str, None] = "071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emergency_funds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("target_months", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("current_amount", sa.Numeric(precision=15, scale=2), nullable=False, server_default="0"),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("monthly_contribution", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_emergency_funds_workspace_id", "emergency_funds", ["workspace_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_emergency_funds_workspace_id", table_name="emergency_funds")
    op.drop_table("emergency_funds")
