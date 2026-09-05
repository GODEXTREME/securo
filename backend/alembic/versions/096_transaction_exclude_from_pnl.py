"""keep selected transactions in balances but out of P/L calculations

Revision ID: 096
Revises: 095
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "096"
down_revision: Union[str, None] = "095"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "exclude_from_pnl",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "exclude_from_pnl")
