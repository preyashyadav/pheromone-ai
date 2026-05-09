"""Phase 9 recall lifecycle state machine expansion

Revision ID: 20260508_000005
Revises: 20260508_000004
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op


revision = "20260508_000005"
down_revision = "20260508_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres enums are append-only; Phase 9 expands the lifecycle labels used by orchestration.
    # These values are stored in `recall_cases.state`.
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'intake_queued';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'intake_running';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'requires_human_review';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'scope_review_pending';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'scope_review_approved';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'trace_queued';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'trace_running';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'trace_completed';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'match_queued';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'match_running';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'match_completed';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'ops_running';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'ops_completed';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'comms_running';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'comms_completed';")
    op.execute("ALTER TYPE recall_case_state ADD VALUE IF NOT EXISTS 'awaiting_manager_approval';")


def downgrade() -> None:
    # Enum value removal isn't reversible; Phase 1 downgrade drops the type anyway.
    pass

