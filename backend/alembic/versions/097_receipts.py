"""consumer receipts (NFC-e): stores, receipts, items and per-workspace links

Revision ID: 097
Revises: 096
Create Date: 2026-09-06

Four new tables, no change to any existing one. Three of them are
instance-wide — a receipt is a public document to whoever holds its
access key, and caching it once per key is what keeps a state portal
from being asked twice and lets two workspaces share one price history.
The fourth, `receipt_links`, is the only workspace-scoped one: it is the
personal fact of having scanned a note, and the row "not my purchase" and
a transaction match hang off.

The fetch queue is columns on `receipts` (`status`, `attempts`,
`next_attempt_at`, `locked_at`) rather than a table of its own: there is
exactly one job per key.

The catalogue (`products`, `product_aliases`, `price_points`) is the next
migration; `receipt_items` gains its `product_id` there, not here.

Downgrade drops all four. Nothing outside them references them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "097"
down_revision: Union[str, None] = "096"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cnpj", sa.String(length=14), nullable=False),
        sa.Column("cnpj_root", sa.String(length=8), nullable=False),
        sa.Column("ie", sa.String(length=20), nullable=True),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("trade_name", sa.String(length=255), nullable=True),
        sa.Column("street", sa.String(length=255), nullable=True),
        sa.Column("number", sa.String(length=30), nullable=True),
        sa.Column("district", sa.String(length=120), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("uf", sa.String(length=2), nullable=True),
        sa.Column("zip", sa.String(length=10), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stores_cnpj", "stores", ["cnpj"], unique=True)
    op.create_index("ix_stores_cnpj_root", "stores", ["cnpj_root"])

    op.create_table(
        "receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_key", sa.String(length=44), nullable=False),
        sa.Column("c_uf", sa.String(length=2), nullable=False),
        sa.Column("uf", sa.String(length=2), nullable=False),
        sa.Column("model", sa.String(length=2), nullable=False, server_default="65"),
        sa.Column("series", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("tp_amb", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("tp_emis", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("qr_version", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("issuer_cnpj", sa.String(length=14), nullable=False),
        sa.Column("qr_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("status_reason", sa.String(length=32), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.SmallInteger(), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("protocol", sa.String(length=20), nullable=True),
        sa.Column("items_count", sa.SmallInteger(), nullable=True),
        sa.Column("products_total", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("discount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("addition", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("shipping", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("total", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("approx_taxes", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("payments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("customer_cpf_hash", sa.String(length=64), nullable=True),
        sa.Column("variation_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_html", sa.LargeBinary(), nullable=True),
        sa.Column("raw_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_receipts_access_key", "receipts", ["access_key"], unique=True)
    op.create_index("ix_receipts_issuer_cnpj", "receipts", ["issuer_cnpj"])
    op.create_index("ix_receipts_status", "receipts", ["status"])
    op.create_index("ix_receipts_due", "receipts", ["status", "next_attempt_at"])
    op.create_index("ix_receipts_store_issued", "receipts", ["store_id", "issued_at"])

    op.create_table(
        "receipt_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("product_code", sa.String(length=60), nullable=False),
        sa.Column("gtin", sa.String(length=14), nullable=True),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("ncm", sa.String(length=8), nullable=True),
        sa.Column("cfop", sa.String(length=4), nullable=True),
        sa.Column("unit", sa.String(length=6), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column("total", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("discount", sa.Numeric(precision=15, scale=2), nullable=False, server_default="0"),
        sa.Column("unit_price_corrected", sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", "ordinal", name="uq_receipt_items_receipt_ordinal"),
    )
    op.create_index("ix_receipt_items_receipt_id", "receipt_items", ["receipt_id"])
    op.create_index("ix_receipt_items_gtin", "receipt_items", ["gtin"])

    op.create_table(
        "receipt_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("not_my_purchase", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", "workspace_id", name="uq_receipt_links_receipt_workspace"),
    )
    op.create_index("ix_receipt_links_receipt_id", "receipt_links", ["receipt_id"])
    op.create_index("ix_receipt_links_workspace_id", "receipt_links", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("receipt_links")
    op.drop_table("receipt_items")
    op.drop_table("receipts")
    op.drop_table("stores")
