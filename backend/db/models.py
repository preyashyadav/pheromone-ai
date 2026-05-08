from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(tz=datetime.UTC)


# -----------------------------
# Pydantic JSONB contracts
# -----------------------------


class IngredientLotUse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_lot_id: uuid.UUID
    quantity_kg: float = Field(ge=0)


class RecipeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: uuid.UUID
    quantity_g: float = Field(ge=0)


class TransactionLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finished_product_id: uuid.UUID
    quantity_units: int = Field(ge=1)
    # Optional forward-looking capture of lot code at checkout (~20% in synthetic data)
    finished_product_lot_id: uuid.UUID | None = None


class CustomerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = "en"
    kids_at_home: bool = False
    immunocompromised: bool = False
    allergies: list[str] = Field(default_factory=list)
    consent_sms: bool = False
    consent_email: bool = False


class RecallSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["openfda", "usda_rss", "supplier", "internal"]
    external_id: str | None = None
    title: str
    summary: str
    published_at_utc: datetime
    hazard: str | None = None
    affected_upcs: list[str] = Field(default_factory=list)
    affected_facility_ids: list[uuid.UUID] = Field(default_factory=list)
    affected_ingredient_lot_ids: list[uuid.UUID] = Field(default_factory=list)


class BlastRadiusSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_lot_ids: list[uuid.UUID] = Field(default_factory=list)
    finished_product_lot_ids: list[uuid.UUID] = Field(default_factory=list)
    pallet_ids: list[uuid.UUID] = Field(default_factory=list)
    store_ids: list[uuid.UUID] = Field(default_factory=list)
    transaction_ids: list[uuid.UUID] = Field(default_factory=list)


class PaymentType(str, enum.Enum):
    loyalty = "loyalty"
    credit_with_email = "credit_with_email"
    cash = "cash"
    third_party = "third_party"


class ContaminationStatus(str, enum.Enum):
    unknown = "unknown"
    suspected = "suspected"
    confirmed_contaminated = "confirmed_contaminated"
    confirmed_clean = "confirmed_clean"


class RecallCaseState(str, enum.Enum):
    # 20-state machine will be defined in orchestration/state.py later; store raw label now.
    created = "created"
    intake_parsed = "intake_parsed"
    tracing = "tracing"
    traced = "traced"
    scoring = "scoring"
    scored = "scored"
    ops_queueing = "ops_queueing"
    comms_drafting = "comms_drafting"
    awaiting_approval = "awaiting_approval"
    closed = "closed"


# -----------------------------
# ORM tables
# -----------------------------


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ingredients: Mapped[list["Ingredient"]] = relationship(back_populates="supplier")


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    parent_ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    supplier: Mapped["Supplier | None"] = relationship(back_populates="ingredients")
    parent: Mapped["Ingredient | None"] = relationship(remote_side=[id])


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    facilities: Mapped[list["Facility"]] = relationship(back_populates="manufacturer")
    finished_products: Mapped[list["FinishedProduct"]] = relationship(back_populates="manufacturer")


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manufacturer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plant_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    manufacturer: Mapped["Manufacturer"] = relationship(back_populates="facilities")
    ingredient_lots: Mapped[list["IngredientLot"]] = relationship(back_populates="facility")
    production_runs: Mapped[list["ProductionRun"]] = relationship(back_populates="facility")


class IngredientLot(Base):
    __tablename__ = "ingredient_lots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    lot_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contamination_status: Mapped[ContaminationStatus] = mapped_column(
        Enum(ContaminationStatus, name="contamination_status"),
        nullable=False,
        default=ContaminationStatus.unknown,
    )
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    facility: Mapped["Facility"] = relationship(back_populates="ingredient_lots")


class ProductionRun(Base):
    __tablename__ = "production_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingredient_lots_used: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    facility: Mapped["Facility"] = relationship(back_populates="production_runs")
    finished_product_lots: Mapped[list["FinishedProductLot"]] = relationship(
        back_populates="production_run"
    )

    __table_args__ = (
        CheckConstraint("ended_at >= started_at", name="ck_production_run_time"),
    )


class FinishedProduct(Base):
    __tablename__ = "finished_products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manufacturer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    upc: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    ingredient_recipe: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    manufacturer: Mapped["Manufacturer"] = relationship(back_populates="finished_products")
    lots: Mapped[list["FinishedProductLot"]] = relationship(back_populates="finished_product")


class FinishedProductLot(Base):
    __tablename__ = "finished_product_lots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finished_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("finished_products.id", ondelete="CASCADE"), nullable=False
    )
    production_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("production_runs.id", ondelete="CASCADE"), nullable=False
    )
    lot_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    produced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    best_by_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    finished_product: Mapped["FinishedProduct"] = relationship(back_populates="lots")
    production_run: Mapped["ProductionRun"] = relationship(back_populates="finished_product_lots")
    pallets: Mapped[list["Pallet"]] = relationship(back_populates="finished_product_lot")


class Distributor(Base):
    __tablename__ = "distributors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    warehouses: Mapped[list["DistributorWarehouse"]] = relationship(back_populates="distributor")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="distributor")


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manufacturer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False
    )
    distributor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("distributors.id", ondelete="CASCADE"), nullable=False
    )
    shipped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    distributor: Mapped["Distributor"] = relationship(back_populates="shipments")
    pallets: Mapped[list["Pallet"]] = relationship(back_populates="shipment")


class DistributorWarehouse(Base):
    __tablename__ = "distributor_warehouses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    distributor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("distributors.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    distributor: Mapped["Distributor"] = relationship(back_populates="warehouses")
    store_shipments: Mapped[list["StoreShipment"]] = relationship(back_populates="warehouse")


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    store_shipments: Mapped[list["StoreShipment"]] = relationship(back_populates="store")
    stocking_events: Mapped[list["StockingEvent"]] = relationship(back_populates="store")
    transactions: Mapped[list["PosTransaction"]] = relationship(back_populates="store")
    refrigeration_zones: Mapped[list["RefrigerationZone"]] = relationship(back_populates="store")


class StoreShipment(Base):
    __tablename__ = "store_shipments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("distributor_warehouses.id", ondelete="CASCADE"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    shipped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    warehouse: Mapped["DistributorWarehouse"] = relationship(back_populates="store_shipments")
    store: Mapped["Store"] = relationship(back_populates="store_shipments")
    pallets: Mapped[list["Pallet"]] = relationship(back_populates="store_shipment")


class Pallet(Base):
    __tablename__ = "pallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finished_product_lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("finished_product_lots.id", ondelete="CASCADE"),
        nullable=False,
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    store_shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("store_shipments.id", ondelete="SET NULL"), nullable=True
    )
    units_total: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    finished_product_lot: Mapped["FinishedProductLot"] = relationship(back_populates="pallets")
    shipment: Mapped["Shipment | None"] = relationship(back_populates="pallets")
    store_shipment: Mapped["StoreShipment | None"] = relationship(back_populates="pallets")
    stocking_events: Mapped[list["StockingEvent"]] = relationship(back_populates="pallet")


class StockingEvent(Base):
    __tablename__ = "stocking_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    pallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pallets.id", ondelete="CASCADE"), nullable=False
    )
    finished_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("finished_products.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    units_added: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    store: Mapped["Store"] = relationship(back_populates="stocking_events")
    pallet: Mapped["Pallet"] = relationship(back_populates="stocking_events")

    __table_args__ = (
        Index("ix_stocking_store_product_time", "store_id", "finished_product_id", "timestamp"),
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loyalty_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    email_hash: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    transactions: Mapped[list["PosTransaction"]] = relationship(back_populates="customer")


class InstitutionalAccount(Base):
    __tablename__ = "institutional_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PosTransaction(Base):
    __tablename__ = "pos_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payment_type: Mapped[PaymentType] = mapped_column(
        Enum(PaymentType, name="payment_type"), nullable=False
    )
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    store: Mapped["Store"] = relationship(back_populates="transactions")
    customer: Mapped["Customer | None"] = relationship(back_populates="transactions")

    __table_args__ = (Index("ix_transactions_store_time", "store_id", "timestamp"),)


class RefrigerationZone(Base):
    __tablename__ = "refrigeration_zones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    store: Mapped["Store"] = relationship(back_populates="refrigeration_zones")
    events: Mapped[list["RefrigerationEvent"]] = relationship(back_populates="zone")

    __table_args__ = (UniqueConstraint("store_id", "name", name="uq_zone_store_name"),)


class RefrigerationEvent(Base):
    __tablename__ = "refrigeration_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refrigeration_zones.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    zone: Mapped["RefrigerationZone"] = relationship(back_populates="events")


class RecallCase(Base):
    __tablename__ = "recall_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state: Mapped[RecallCaseState] = mapped_column(
        Enum(RecallCaseState, name="recall_case_state"),
        nullable=False,
        default=RecallCaseState.created,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    spec: Mapped["RecallSpecRow | None"] = relationship(
        back_populates="recall_case",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    scope_versions: Mapped[list["RecallScopeVersion"]] = relationship(
        back_populates="recall_case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RecallSpecRow(Base):
    __tablename__ = "recall_specs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    recall_case: Mapped["RecallCase"] = relationship(back_populates="spec", passive_deletes=True)


class AffectedBlastRadiusSnapshot(Base):
    __tablename__ = "affected_blast_radius_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("recall_case_id", "version", name="uq_blast_version"),)


class ScoredTransaction(Base):
    __tablename__ = "scored_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_transactions.id", ondelete="CASCADE"), nullable=False
    )
    affected_probability: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("recall_case_id", "transaction_id", name="uq_score_case_tx"),)


class EmployeeTask(Base):
    __tablename__ = "employee_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NotificationDraft(Base):
    __tablename__ = "notification_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_tier: Mapped[str] = mapped_column(String(64), nullable=False)
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False
    )
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ComplianceLog(Base):
    __tablename__ = "compliance_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_compliance_case_created", "recall_case_id", "created_at"),)


class RecallScopeVersion(Base):
    __tablename__ = "recall_scope_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recall_cases.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    recall_case: Mapped["RecallCase"] = relationship(back_populates="scope_versions", passive_deletes=True)

    __table_args__ = (UniqueConstraint("recall_case_id", "version", name="uq_scope_version"),)


# Indexes on every FK are created in the migration for deterministic naming.
