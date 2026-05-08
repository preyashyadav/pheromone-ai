"""Phase 7: pos_blocks table.

Revision ID: 20260508_000004
Revises: 20260508_000003
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260508_000004"
down_revision = "20260508_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pos_blocks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("upc", sa.String(length=32), nullable=False),
        sa.Column("lot_constraint", sa.String(length=128), nullable=True),
        sa.Column("active_until", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_pos_blocks_store_id", "pos_blocks", ["store_id"])
    op.create_index("ix_pos_blocks_upc", "pos_blocks", ["upc"])


def downgrade() -> None:
    op.drop_index("ix_pos_blocks_upc", table_name="pos_blocks")
    op.drop_index("ix_pos_blocks_store_id", table_name="pos_blocks")
    op.drop_table("pos_blocks")

