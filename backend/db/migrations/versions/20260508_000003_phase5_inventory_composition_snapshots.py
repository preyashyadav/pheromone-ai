"""
Phase 5: inventory composition snapshot caching.

Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260508_000003"
down_revision = "20260508_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_composition_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finished_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_hour", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("composition", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finished_product_id"], ["finished_products.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "store_id",
            "finished_product_id",
            "snapshot_hour",
            name="uq_composition_snapshot_store_product_hour",
        ),
    )
    op.create_index(
        "ix_comp_snap_store_product_hour",
        "inventory_composition_snapshots",
        ["store_id", "finished_product_id", "snapshot_hour"],
    )


def downgrade() -> None:
    op.drop_index("ix_comp_snap_store_product_hour", table_name="inventory_composition_snapshots")
    op.drop_table("inventory_composition_snapshots")

