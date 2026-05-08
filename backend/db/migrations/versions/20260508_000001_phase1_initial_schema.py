"""Phase 1 initial schema

Revision ID: 20260508_000001
Revises:
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260508_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "ingredients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("parent_ingredient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ingredients_supplier_id", "ingredients", ["supplier_id"])
    op.create_index("ix_ingredients_parent_ingredient_id", "ingredients", ["parent_ingredient_id"])

    op.create_table(
        "manufacturers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "facilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("manufacturer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("plant_code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_facilities_manufacturer_id", "facilities", ["manufacturer_id"])

    op.execute(
        """
        DO $$
        BEGIN
          CREATE TYPE contamination_status AS ENUM (
            'unknown',
            'suspected',
            'confirmed_contaminated',
            'confirmed_clean'
          );
        EXCEPTION
          WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    contamination_status = postgresql.ENUM(
        "unknown",
        "suspected",
        "confirmed_contaminated",
        "confirmed_clean",
        name="contamination_status",
        create_type=False,
    )

    op.create_table(
        "ingredient_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ingredient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lot_code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("contamination_status", contamination_status, nullable=False, server_default="unknown"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ingredient_lots_ingredient_id", "ingredient_lots", ["ingredient_id"])
    op.create_index("ix_ingredient_lots_facility_id", "ingredient_lots", ["facility_id"])

    op.create_table(
        "production_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ingredient_lots_used", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("ended_at >= started_at", name="ck_production_run_time"),
    )
    op.create_index("ix_production_runs_facility_id", "production_runs", ["facility_id"])

    op.create_table(
        "finished_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("manufacturer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("upc", sa.String(length=32), nullable=False, unique=True),
        sa.Column("ingredient_recipe", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_finished_products_manufacturer_id", "finished_products", ["manufacturer_id"])

    op.create_table(
        "finished_product_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("finished_product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("finished_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("production_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lot_code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("produced_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("best_by_date", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_finished_product_lots_finished_product_id", "finished_product_lots", ["finished_product_id"])
    op.create_index("ix_finished_product_lots_production_run_id", "finished_product_lots", ["production_run_id"])

    op.create_table(
        "distributors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "shipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("manufacturer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("distributor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("distributors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shipped_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("arrived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_shipments_manufacturer_id", "shipments", ["manufacturer_id"])
    op.create_index("ix_shipments_distributor_id", "shipments", ["distributor_id"])

    op.create_table(
        "distributor_warehouses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("distributor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("distributors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_distributor_warehouses_distributor_id", "distributor_warehouses", ["distributor_id"])

    op.create_table(
        "stores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "store_shipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("distributor_warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shipped_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("arrived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_store_shipments_warehouse_id", "store_shipments", ["warehouse_id"])
    op.create_index("ix_store_shipments_store_id", "store_shipments", ["store_id"])

    op.create_table(
        "pallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("finished_product_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("finished_product_lots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("store_shipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("store_shipments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("units_total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_pallets_finished_product_lot_id", "pallets", ["finished_product_lot_id"])
    op.create_index("ix_pallets_shipment_id", "pallets", ["shipment_id"])
    op.create_index("ix_pallets_store_shipment_id", "pallets", ["store_shipment_id"])

    op.create_table(
        "stocking_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pallet_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pallets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finished_product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("finished_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("units_added", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_stocking_events_store_id", "stocking_events", ["store_id"])
    op.create_index("ix_stocking_events_pallet_id", "stocking_events", ["pallet_id"])
    op.create_index("ix_stocking_events_finished_product_id", "stocking_events", ["finished_product_id"])
    op.create_index("ix_stocking_store_product_time", "stocking_events", ["store_id", "finished_product_id", "timestamp"])

    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("loyalty_id", sa.String(length=64), nullable=True, unique=True),
        sa.Column("email_hash", sa.String(length=128), nullable=True, unique=True),
        sa.Column("phone_hash", sa.String(length=128), nullable=True, unique=True),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "institutional_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_institutional_accounts_customer_id", "institutional_accounts", ["customer_id"])

    op.execute(
        """
        DO $$
        BEGIN
          CREATE TYPE payment_type AS ENUM (
            'loyalty',
            'credit_with_email',
            'cash',
            'third_party'
          );
        EXCEPTION
          WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    payment_type = postgresql.ENUM(
        "loyalty",
        "credit_with_email",
        "cash",
        "third_party",
        name="payment_type",
        create_type=False,
    )

    op.create_table(
        "pos_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("payment_type", payment_type, nullable=False),
        sa.Column("line_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_pos_transactions_store_id", "pos_transactions", ["store_id"])
    op.create_index("ix_pos_transactions_customer_id", "pos_transactions", ["customer_id"])
    op.create_index("ix_transactions_store_time", "pos_transactions", ["store_id", "timestamp"])

    op.create_table(
        "refrigeration_zones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("store_id", "name", name="uq_zone_store_name"),
    )
    op.create_index("ix_refrigeration_zones_store_id", "refrigeration_zones", ["store_id"])

    op.create_table(
        "refrigeration_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("refrigeration_zones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_refrigeration_events_zone_id", "refrigeration_events", ["zone_id"])

    op.execute(
        """
        DO $$
        BEGIN
          CREATE TYPE recall_case_state AS ENUM (
            'created',
            'intake_parsed',
            'tracing',
            'traced',
            'scoring',
            'scored',
            'ops_queueing',
            'comms_drafting',
            'awaiting_approval',
            'closed'
          );
        EXCEPTION
          WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    recall_case_state = postgresql.ENUM(
        "created",
        "intake_parsed",
        "tracing",
        "traced",
        "scoring",
        "scored",
        "ops_queueing",
        "comms_drafting",
        "awaiting_approval",
        "closed",
        name="recall_case_state",
        create_type=False,
    )

    op.create_table(
        "recall_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("state", recall_case_state, nullable=False, server_default="created"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "recall_specs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_recall_specs_recall_case_id", "recall_specs", ["recall_case_id"])

    op.create_table(
        "affected_blast_radius_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("recall_case_id", "version", name="uq_blast_version"),
    )
    op.create_index("ix_affected_blast_radius_snapshots_recall_case_id", "affected_blast_radius_snapshots", ["recall_case_id"])

    op.create_table(
        "scored_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pos_transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("affected_probability", sa.Integer(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("recall_case_id", "transaction_id", name="uq_score_case_tx"),
    )
    op.create_index("ix_scored_transactions_recall_case_id", "scored_transactions", ["recall_case_id"])
    op.create_index("ix_scored_transactions_transaction_id", "scored_transactions", ["transaction_id"])

    op.create_table(
        "employee_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_employee_tasks_recall_case_id", "employee_tasks", ["recall_case_id"])

    op.create_table(
        "notification_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("confidence_tier", sa.String(length=64), nullable=False),
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_notification_drafts_recall_case_id", "notification_drafts", ["recall_case_id"])
    op.create_index("ix_notification_drafts_customer_id", "notification_drafts", ["customer_id"])

    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_approvals_recall_case_id", "approvals", ["recall_case_id"])

    op.create_table(
        "compliance_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_compliance_log_recall_case_id", "compliance_log", ["recall_case_id"])
    op.create_index("ix_compliance_case_created", "compliance_log", ["recall_case_id", "created_at"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION compliance_log_no_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'compliance_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_compliance_log_no_update
        BEFORE UPDATE ON compliance_log
        FOR EACH ROW EXECUTE FUNCTION compliance_log_no_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_compliance_log_no_delete
        BEFORE DELETE ON compliance_log
        FOR EACH ROW EXECUTE FUNCTION compliance_log_no_mutation();
        """
    )

    op.create_table(
        "recall_scope_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recall_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("recall_case_id", "version", name="uq_scope_version"),
    )
    op.create_index("ix_recall_scope_versions_recall_case_id", "recall_scope_versions", ["recall_case_id"])


def downgrade() -> None:
    op.drop_index("ix_recall_scope_versions_recall_case_id", table_name="recall_scope_versions")
    op.drop_table("recall_scope_versions")

    op.execute("DROP TRIGGER IF EXISTS trg_compliance_log_no_delete ON compliance_log;")
    op.execute("DROP TRIGGER IF EXISTS trg_compliance_log_no_update ON compliance_log;")
    op.execute("DROP FUNCTION IF EXISTS compliance_log_no_mutation();")
    op.drop_index("ix_compliance_case_created", table_name="compliance_log")
    op.drop_index("ix_compliance_log_recall_case_id", table_name="compliance_log")
    op.drop_table("compliance_log")

    op.drop_index("ix_approvals_recall_case_id", table_name="approvals")
    op.drop_table("approvals")

    op.drop_index("ix_notification_drafts_customer_id", table_name="notification_drafts")
    op.drop_index("ix_notification_drafts_recall_case_id", table_name="notification_drafts")
    op.drop_table("notification_drafts")

    op.drop_index("ix_employee_tasks_recall_case_id", table_name="employee_tasks")
    op.drop_table("employee_tasks")

    op.drop_index("ix_scored_transactions_transaction_id", table_name="scored_transactions")
    op.drop_index("ix_scored_transactions_recall_case_id", table_name="scored_transactions")
    op.drop_table("scored_transactions")

    op.drop_index(
        "ix_affected_blast_radius_snapshots_recall_case_id",
        table_name="affected_blast_radius_snapshots",
    )
    op.drop_table("affected_blast_radius_snapshots")

    op.drop_index("ix_recall_specs_recall_case_id", table_name="recall_specs")
    op.drop_table("recall_specs")

    op.drop_table("recall_cases")

    op.drop_index("ix_refrigeration_events_zone_id", table_name="refrigeration_events")
    op.drop_table("refrigeration_events")

    op.drop_index("ix_refrigeration_zones_store_id", table_name="refrigeration_zones")
    op.drop_table("refrigeration_zones")

    op.drop_index("ix_transactions_store_time", table_name="pos_transactions")
    op.drop_index("ix_pos_transactions_customer_id", table_name="pos_transactions")
    op.drop_index("ix_pos_transactions_store_id", table_name="pos_transactions")
    op.drop_table("pos_transactions")

    op.drop_index("ix_institutional_accounts_customer_id", table_name="institutional_accounts")
    op.drop_table("institutional_accounts")

    op.drop_table("customers")

    op.drop_index("ix_stocking_store_product_time", table_name="stocking_events")
    op.drop_index("ix_stocking_events_finished_product_id", table_name="stocking_events")
    op.drop_index("ix_stocking_events_pallet_id", table_name="stocking_events")
    op.drop_index("ix_stocking_events_store_id", table_name="stocking_events")
    op.drop_table("stocking_events")

    op.drop_index("ix_pallets_store_shipment_id", table_name="pallets")
    op.drop_index("ix_pallets_shipment_id", table_name="pallets")
    op.drop_index("ix_pallets_finished_product_lot_id", table_name="pallets")
    op.drop_table("pallets")

    op.drop_index("ix_store_shipments_store_id", table_name="store_shipments")
    op.drop_index("ix_store_shipments_warehouse_id", table_name="store_shipments")
    op.drop_table("store_shipments")

    op.drop_table("stores")

    op.drop_index("ix_distributor_warehouses_distributor_id", table_name="distributor_warehouses")
    op.drop_table("distributor_warehouses")

    op.drop_index("ix_shipments_distributor_id", table_name="shipments")
    op.drop_index("ix_shipments_manufacturer_id", table_name="shipments")
    op.drop_table("shipments")

    op.drop_table("distributors")

    op.drop_index("ix_finished_product_lots_production_run_id", table_name="finished_product_lots")
    op.drop_index("ix_finished_product_lots_finished_product_id", table_name="finished_product_lots")
    op.drop_table("finished_product_lots")

    op.drop_index("ix_finished_products_manufacturer_id", table_name="finished_products")
    op.drop_table("finished_products")

    op.drop_index("ix_production_runs_facility_id", table_name="production_runs")
    op.drop_table("production_runs")

    op.drop_index("ix_ingredient_lots_facility_id", table_name="ingredient_lots")
    op.drop_index("ix_ingredient_lots_ingredient_id", table_name="ingredient_lots")
    op.drop_table("ingredient_lots")

    op.drop_index("ix_facilities_manufacturer_id", table_name="facilities")
    op.drop_table("facilities")

    op.drop_table("manufacturers")

    op.drop_index("ix_ingredients_parent_ingredient_id", table_name="ingredients")
    op.drop_index("ix_ingredients_supplier_id", table_name="ingredients")
    op.drop_table("ingredients")

    op.drop_table("suppliers")

    op.execute("DROP TYPE IF EXISTS recall_case_state;")
    op.execute("DROP TYPE IF EXISTS payment_type;")
    op.execute("DROP TYPE IF EXISTS contamination_status;")
