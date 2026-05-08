"""Phase 3 raw notice ingestion primitives

Revision ID: 20260508_000002
Revises: 20260508_000001
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260508_000002"
down_revision = "20260508_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Internal/ingestion state needed before Intake Agent runs.
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'signal_detected';")

    op.add_column("recall_cases", sa.Column("source_type", sa.String(length=64), nullable=True))
    op.add_column(
        "recall_cases",
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "recall_cases",
        sa.Column("source_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_recall_cases_store_id", "recall_cases", ["store_id"])

    op.create_table(
        "raw_recall_notices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("source_type", "external_id", name="uq_raw_recall_notice_source_external"),
    )
    op.create_index("ix_raw_recall_notices_source_type", "raw_recall_notices", ["source_type"])
    op.create_index("ix_raw_recall_notices_external_id", "raw_recall_notices", ["external_id"])

    op.create_table(
        "unverified_recall_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_unverified_recall_signals_created_at", "unverified_recall_signals", ["created_at"])


def downgrade() -> None:
    # Enum value removal isn't reversible; Phase 1 downgrade drops the type anyway.
    op.drop_index("ix_unverified_recall_signals_created_at", table_name="unverified_recall_signals")
    op.drop_table("unverified_recall_signals")

    op.drop_index("ix_raw_recall_notices_external_id", table_name="raw_recall_notices")
    op.drop_index("ix_raw_recall_notices_source_type", table_name="raw_recall_notices")
    op.drop_table("raw_recall_notices")

    op.drop_index("ix_recall_cases_store_id", table_name="recall_cases")
    op.drop_column("recall_cases", "source_details")
    op.drop_column("recall_cases", "store_id")
    op.drop_column("recall_cases", "source_type")
