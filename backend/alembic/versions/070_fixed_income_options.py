"""fixed income options (renda fixa comparator)

Revision ID: 070
Revises: 069
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fixed_income_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("institution", sa.String(length=120), nullable=True),
        sa.Column("product_type", sa.String(length=40), nullable=False, server_default="CDB"),
        sa.Column("rate_kind", sa.String(length=20), nullable=False, server_default="cdi"),
        sa.Column("rate", sa.Numeric(precision=8, scale=2), nullable=False, server_default="0"),
        sa.Column("liquidity", sa.String(length=20), nullable=False, server_default="daily"),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("min_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("tax_exempt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_fixed_income_options_workspace_id", "fixed_income_options", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_fixed_income_options_workspace_id", table_name="fixed_income_options")
    op.drop_table("fixed_income_options")
