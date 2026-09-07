"""the credential a capture bookmarklet carries

Revision ID: 099
Revises: 098
Create Date: 2026-09-07

A bookmarklet posts a note's page from the state portal's own origin, so
it cannot send the session cookie. It sends one of these instead: a
secret scoped to one workspace and one endpoint, stored as a sha256 hash
and revocable on its own.

Downgrade drops the table; the tokens are secrets, not data worth
keeping, and a new one is a click.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "099"
down_revision: Union[str, None] = "098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "receipt_capture_tokens",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("label", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_receipt_capture_tokens_workspace_id", "receipt_capture_tokens", ["workspace_id"])
    op.create_index("ix_receipt_capture_tokens_user_id", "receipt_capture_tokens", ["user_id"])
    op.create_index("ix_receipt_capture_tokens_token_hash", "receipt_capture_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_receipt_capture_tokens_token_hash", table_name="receipt_capture_tokens")
    op.drop_index("ix_receipt_capture_tokens_user_id", table_name="receipt_capture_tokens")
    op.drop_index("ix_receipt_capture_tokens_workspace_id", table_name="receipt_capture_tokens")
    op.drop_table("receipt_capture_tokens")
