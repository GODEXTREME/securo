"""the catalogue: products, aliases and price points

Revision ID: 098
Revises: 097
Create Date: 2026-09-06

Three new instance-wide tables and the columns that tie a receipt line to
them. `receipt_items.product_id` is filled by the matcher after the note
is authorised. `variation_summary` moves from `receipts` to
`receipt_links`: "what you paid last time" is a fact about one workspace,
and the note is shared by every workspace that scanned it.

Downgrade drops the three tables and the added columns, and puts the
column back on `receipts` (empty).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "098"
down_revision: Union[str, None] = "097"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("gtin", sa.String(length=14), nullable=True),
        sa.Column("chain_root", sa.String(length=8), nullable=True),
        sa.Column("fingerprint", sa.String(length=200), nullable=False),
        sa.Column("fingerprint_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("size_value", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("size_unit", sa.String(length=4), nullable=True),
        sa.Column("pack_count", sa.SmallInteger(), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("enrichment_source", sa.String(length=30), nullable=True),
        sa.Column("merged_into_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merged_into_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_gtin", "products", ["gtin"], unique=True)
    op.create_index("ix_products_chain_root", "products", ["chain_root"])
    op.create_index("ix_products_fingerprint", "products", ["fingerprint"])

    op.create_table(
        "product_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=6), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=False, server_default="1.00"),
        sa.Column("origin", sa.String(length=12), nullable=False, server_default="sefaz"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "value", name="uq_product_aliases_kind_value"),
    )
    op.create_index("ix_product_aliases_product_id", "product_aliases", ["product_id"])

    op.add_column("receipt_items", sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("receipt_items", sa.Column("size_value", sa.Numeric(precision=12, scale=3), nullable=True))
    op.add_column("receipt_items", sa.Column("size_unit", sa.String(length=4), nullable=True))
    op.add_column("receipt_items", sa.Column("pack_count", sa.SmallInteger(), nullable=True))
    op.add_column("receipt_items", sa.Column("normalized_price", sa.Numeric(precision=15, scale=4), nullable=True))
    op.add_column("receipt_items", sa.Column("base_unit", sa.String(length=3), nullable=True))
    op.add_column(
        "receipt_items",
        sa.Column("comparable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_foreign_key(
        "fk_receipt_items_product_id", "receipt_items", "products", ["product_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_receipt_items_product_id", "receipt_items", ["product_id"])

    op.create_table(
        "price_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("unit", sa.String(length=6), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column("normalized_price", sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column("base_unit", sa.String(length=3), nullable=True),
        sa.Column("comparable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_outlier", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=False, server_default="sefaz_html"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["receipt_item_id"], ["receipt_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_item_id", name="uq_price_points_receipt_item"),
    )
    op.create_index("ix_price_points_receipt_id", "price_points", ["receipt_id"])
    op.create_index("ix_price_points_product_id", "price_points", ["product_id"])
    op.create_index("ix_price_points_store_id", "price_points", ["store_id"])
    op.create_index("ix_price_points_product_observed", "price_points", ["product_id", "observed_on"])
    op.create_index(
        "ix_price_points_store_product_observed", "price_points", ["store_id", "product_id", "observed_on"]
    )

    op.add_column(
        "receipt_links", sa.Column("variation_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.drop_column("receipts", "variation_summary")


def downgrade() -> None:
    op.add_column(
        "receipts", sa.Column("variation_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.drop_column("receipt_links", "variation_summary")
    op.drop_table("price_points")
    op.drop_index("ix_receipt_items_product_id", table_name="receipt_items")
    op.drop_constraint("fk_receipt_items_product_id", "receipt_items", type_="foreignkey")
    for column in ("comparable", "base_unit", "normalized_price", "pack_count", "size_unit", "size_value", "product_id"):
        op.drop_column("receipt_items", column)
    op.drop_table("product_aliases")
    op.drop_table("products")
