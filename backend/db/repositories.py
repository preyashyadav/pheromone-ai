from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Iterable

from sqlalchemy import Engine, Select, delete, select, text, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from backend.db.ctes import cte_blast_radius_from_ingredient_lot, cte_inventory_composition_at_time
from backend.db.models import (
    AffectedBlastRadiusSnapshot,
    Approval,
    ComplianceLog,
    Customer,
    Distributor,
    DistributorWarehouse,
    EmployeeTask,
    Facility,
    FinishedProduct,
    FinishedProductLot,
    Ingredient,
    IngredientLot,
    InstitutionalAccount,
    Manufacturer,
    NotificationDraft,
    PosBlock,
    Pallet,
    PosTransaction,
    ProductionRun,
    RecallCase,
    RecallSpecRow,
    RecallScopeVersion,
    RefrigerationEvent,
    RefrigerationZone,
    RawRecallNotice,
    ScoredTransaction,
    Shipment,
    StockingEvent,
    Store,
    StoreShipment,
    Supplier,
    UnverifiedRecallSignal,
    RecallCaseState,
)


@dataclass(frozen=True)
class Repositories:
    supply_chain: "SupplyChainRepository"
    inventory: "InventoryRepository"
    customers: "CustomerRepository"
    recalls: "RecallRepository"


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class BaseRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def session(self) -> Session:
        return self._session_factory()


class SupplyChainRepository(BaseRepository):
    def insert_supplier(self, name: str) -> uuid.UUID:
        with self.session() as s:
            row = Supplier(name=name)
            s.add(row)
            s.commit()
            return row.id

    def insert_min_supply_chain_rows(self) -> dict[str, uuid.UUID]:
        """Used by Phase 1 test #3: insert one row per core supply chain table."""
        with self.session() as s:
            supplier = Supplier(name="Supplier A")
            manufacturer = Manufacturer(name="Maker A")
            distributor = Distributor(name="Distributor A")
            store = Store(name="Store A")
            s.add_all([supplier, manufacturer, distributor, store])
            s.flush()

            ingredient = Ingredient(name="Ingredient A", supplier_id=supplier.id)
            facility = Facility(
                manufacturer_id=manufacturer.id, name="Plant A", plant_code="P1", timezone="UTC"
            )
            s.add_all([ingredient, facility])
            s.flush()

            ingredient_lot = IngredientLot(
                ingredient_id=ingredient.id,
                facility_id=facility.id,
                lot_code="IL-1",
                received_at=s.execute(text("SELECT now()")).scalar_one(),
                meta={},
            )
            # NOTE: `received_at` needs a datetime; set in tests instead.
            s.add(ingredient_lot)
            s.flush()

            production_run = ProductionRun(
                facility_id=facility.id,
                started_at=s.execute(text("SELECT now()")).scalar_one(),
                ended_at=s.execute(text("SELECT now()")).scalar_one(),
                ingredient_lots_used=[{"ingredient_lot_id": str(ingredient_lot.id), "quantity_kg": 1.0}],
            )
            finished_product = FinishedProduct(
                manufacturer_id=manufacturer.id,
                name="Product A",
                upc="000000000001",
                ingredient_recipe=[{"ingredient_id": str(ingredient.id), "quantity_g": 10.0}],
            )
            s.add_all([production_run, finished_product])
            s.flush()

            fpl = FinishedProductLot(
                finished_product_id=finished_product.id,
                production_run_id=production_run.id,
                lot_code="P1-010101-A",
                produced_at=s.execute(text("SELECT now()")).scalar_one(),
                best_by_date=s.execute(text("SELECT now()")).scalar_one(),
            )
            shipment = Shipment(
                manufacturer_id=manufacturer.id,
                distributor_id=distributor.id,
                shipped_at=s.execute(text("SELECT now()")).scalar_one(),
            )
            wh = DistributorWarehouse(distributor_id=distributor.id, name="WH A", timezone="UTC")
            s.add_all([fpl, shipment, wh])
            s.flush()

            ss = StoreShipment(
                warehouse_id=wh.id, store_id=store.id, shipped_at=s.execute(text("SELECT now()")).scalar_one()
            )
            s.add(ss)
            s.flush()

            pallet = Pallet(
                finished_product_lot_id=fpl.id,
                shipment_id=shipment.id,
                store_shipment_id=ss.id,
                units_total=10,
            )
            s.add(pallet)
            s.flush()

            stock = StockingEvent(
                store_id=store.id,
                pallet_id=pallet.id,
                finished_product_id=finished_product.id,
                timestamp=s.execute(text("SELECT now()")).scalar_one(),
                units_added=10,
            )
            s.add(stock)

            s.commit()

            return {
                "supplier_id": supplier.id,
                "ingredient_id": ingredient.id,
                "ingredient_lot_id": ingredient_lot.id,
                "manufacturer_id": manufacturer.id,
                "facility_id": facility.id,
                "production_run_id": production_run.id,
                "finished_product_id": finished_product.id,
                "finished_product_lot_id": fpl.id,
                "distributor_id": distributor.id,
                "warehouse_id": wh.id,
                "store_id": store.id,
                "store_shipment_id": ss.id,
                "shipment_id": shipment.id,
                "pallet_id": pallet.id,
                "stocking_event_id": stock.id,
            }


class InventoryRepository(BaseRepository):
    def blast_radius_transaction_ids_from_ingredient_lot(self, ingredient_lot_id: uuid.UUID) -> list[uuid.UUID]:
        with self.session() as s:
            rows = s.execute(cte_blast_radius_from_ingredient_lot(), {"ingredient_lot_id": ingredient_lot_id}).all()
            return [r[0] for r in rows]

    def inventory_composition_at_time(
        self, store_id: uuid.UUID, finished_product_id: uuid.UUID, as_of: Any
    ) -> list[tuple[uuid.UUID, float]]:
        with self.session() as s:
            rows = s.execute(
                cte_inventory_composition_at_time(),
                {"store_id": store_id, "finished_product_id": finished_product_id, "as_of": as_of},
            ).all()
            return [(r[0], float(r[1])) for r in rows]


class CustomerRepository(BaseRepository):
    def create_customer(self, profile: dict[str, Any]) -> uuid.UUID:
        with self.session() as s:
            row = Customer(profile=profile)
            s.add(row)
            s.commit()
            return row.id


class RecallRepository(BaseRepository):
    def insert_compliance_event(
        self,
        *,
        recall_case_id: uuid.UUID,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        with self.session() as s:
            row = ComplianceLog(
                recall_case_id=recall_case_id,
                event_type=str(event_type),
                message=str(message),
                payload=payload or {},
            )
            s.add(row)
            s.commit()
            return row.id

    def list_compliance_events(self, *, recall_case_id: uuid.UUID, limit: int = 250) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self.session() as s:
            rows = (
                s.execute(
                    select(ComplianceLog.event_type, ComplianceLog.message, ComplianceLog.payload, ComplianceLog.created_at)
                    .where(ComplianceLog.recall_case_id == recall_case_id)
                    .order_by(ComplianceLog.created_at.desc())
                    .limit(limit)
                )
                .all()
            )
        out: list[dict[str, Any]] = []
        for event_type, message, payload, created_at in rows:
            out.append(
                {
                    "event_type": str(event_type),
                    "message": str(message),
                    "payload": payload if isinstance(payload, dict) else {},
                    "created_at": created_at,
                }
            )
        # Return chronological for timeline UIs.
        out.reverse()
        return out

    def list_recall_cases_minimal(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.session() as s:
            rows = (
                s.execute(
                    select(RecallCase.id, RecallCase.state, RecallCase.source_type, RecallCase.source_details, RecallCase.updated_at)
                    .order_by(RecallCase.updated_at.desc())
                    .limit(limit)
                )
                .all()
            )
            ids = [uuid.UUID(str(r[0])) for r in rows]
            if ids:
                spec_rows = s.execute(
                    select(RecallSpecRow.recall_case_id, RecallSpecRow.spec).where(RecallSpecRow.recall_case_id.in_(ids))
                ).all()
            else:
                spec_rows = []
            specs = {uuid.UUID(str(rid)): (spec if isinstance(spec, dict) else None) for rid, spec in spec_rows}

        out: list[dict[str, Any]] = []
        for rid, state, source_type, source_details, updated_at in rows:
            rc_id = uuid.UUID(str(rid))
            spec = specs.get(rc_id) or {}
            out.append(
                {
                    "recall_case_id": rc_id,
                    "state": str(getattr(state, "value", state)),
                    "source_type": source_type,
                    "source_details": source_details if isinstance(source_details, dict) else {},
                    "updated_at": updated_at,
                    "severity": (spec.get("severity") if isinstance(spec, dict) else None),
                    "hazard_type": (spec.get("hazard_type") if isinstance(spec, dict) else None),
                    "recall_id": (spec.get("recall_id") if isinstance(spec, dict) else None),
                }
            )
        return out

    def list_employee_tasks_minimal(self, *, recall_case_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = (
                s.execute(
                    select(EmployeeTask.id, EmployeeTask.task_type, EmployeeTask.payload, EmployeeTask.status, EmployeeTask.created_at)
                    .where(EmployeeTask.recall_case_id == recall_case_id)
                    .order_by(EmployeeTask.created_at.asc())
                )
                .all()
            )
        out: list[dict[str, Any]] = []
        for tid, task_type, payload, status, created_at in rows:
            out.append(
                {
                    "id": uuid.UUID(str(tid)),
                    "task_type": str(task_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "status": str(status),
                    "created_at": created_at,
                }
            )
        return out

    def list_notification_drafts_minimal(self, *, recall_case_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = (
                s.execute(
                    select(
                        NotificationDraft.id,
                        NotificationDraft.customer_id,
                        NotificationDraft.channel,
                        NotificationDraft.confidence_tier,
                        NotificationDraft.draft,
                        NotificationDraft.created_at,
                    )
                    .where(NotificationDraft.recall_case_id == recall_case_id)
                    .order_by(NotificationDraft.created_at.asc())
                )
                .all()
            )
        out: list[dict[str, Any]] = []
        for did, cust_id, channel, tier, draft, created_at in rows:
            out.append(
                {
                    "id": uuid.UUID(str(did)),
                    "customer_id": (uuid.UUID(str(cust_id)) if cust_id is not None else None),
                    "channel": str(channel),
                    "confidence_tier": str(tier),
                    "draft": draft if isinstance(draft, dict) else {},
                    "created_at": created_at,
                }
            )
        return out

    def insert_approval(self, *, recall_case_id: uuid.UUID, approved_by: str, action: str) -> uuid.UUID:
        with self.session() as s:
            row = Approval(recall_case_id=recall_case_id, approved_by=str(approved_by), action=str(action))
            s.add(row)
            s.commit()
            return row.id

    def count_approvals(self, *, recall_case_id: uuid.UUID, action_prefix: str | None = None) -> int:
        with self.session() as s:
            q = select(func.count()).select_from(Approval).where(Approval.recall_case_id == recall_case_id)
            if action_prefix:
                q = q.where(Approval.action.like(f"{action_prefix}%"))
            return int(s.execute(q).scalar_one())

    def create_recall_case(self) -> uuid.UUID:
        with self.session() as s:
            rc = RecallCase()
            s.add(rc)
            s.commit()
            return rc.id

    def create_recall_case_signal_detected(
        self, *, source_type: str, store_id: uuid.UUID | None, source_details: dict[str, Any]
    ) -> uuid.UUID:
        with self.session() as s:
            rc = RecallCase(
                state=RecallCaseState.signal_detected,
                source_type=source_type,
                store_id=store_id,
                source_details=source_details,
            )
            s.add(rc)
            s.commit()
            return rc.id

    def upsert_raw_recall_notice(
        self,
        *,
        source_type: str,
        external_id: str | None,
        source_url: str | None,
        verified: bool,
        published_at: datetime | None,
        raw_json: dict[str, Any],
        raw_text: str,
    ) -> uuid.UUID:
        with self.session() as s:
            stmt = (
                pg_insert(RawRecallNotice)
                .values(
                    source_type=source_type,
                    external_id=external_id,
                    source_url=source_url,
                    verified=verified,
                    published_at=published_at,
                    raw_json=raw_json,
                    raw_text=raw_text,
                )
                .on_conflict_do_nothing(constraint="uq_raw_recall_notice_source_external")
                .returning(RawRecallNotice.id)
            )
            inserted = s.execute(stmt).scalar_one_or_none()
            if inserted is not None:
                s.commit()
                return inserted

            existing = (
                s.execute(
                    select(RawRecallNotice.id).where(
                        RawRecallNotice.source_type == source_type,
                        RawRecallNotice.external_id == external_id,
                    )
                )
                .scalar_one()
            )
            return existing

    def create_pos_block(
        self,
        *,
        store_id: uuid.UUID,
        upc: str,
        lot_constraint: str | None,
        active_until: datetime,
    ) -> uuid.UUID:
        with self.session() as s:
            row = PosBlock(
                store_id=store_id,
                upc=upc,
                lot_constraint=lot_constraint,
                active_until=active_until,
            )
            s.add(row)
            s.commit()
            return row.id

    def count_raw_recall_notices(self) -> int:
        with self.session() as s:
            return int(s.execute(select(func.count()).select_from(RawRecallNotice)).scalar_one())

    def list_raw_recall_notice_external_ids(self, *, source_type: str) -> list[str]:
        with self.session() as s:
            rows = s.execute(
                select(RawRecallNotice.external_id).where(RawRecallNotice.source_type == source_type)
            ).all()
            return [r[0] for r in rows if r[0] is not None]

    def upsert_unverified_recall_signal(
        self, *, source_url: str | None, reason: str, raw_payload: dict[str, Any]
    ) -> uuid.UUID:
        content = json.dumps(
            {"source_url": source_url, "reason": reason, "raw_payload": raw_payload},
            sort_keys=True,
            default=str,
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self.session() as s:
            stmt = (
                pg_insert(UnverifiedRecallSignal)
                .values(source_url=source_url, reason=reason, content_hash=content_hash, raw_payload=raw_payload)
                .on_conflict_do_nothing(index_elements=[UnverifiedRecallSignal.content_hash])
                .returning(UnverifiedRecallSignal.id)
            )
            inserted = s.execute(stmt).scalar_one_or_none()
            if inserted is not None:
                s.commit()
                return inserted

            existing = (
                s.execute(select(UnverifiedRecallSignal.id).where(UnverifiedRecallSignal.content_hash == content_hash))
                .scalar_one()
            )
            return existing

    def attach_spec(self, recall_case_id: uuid.UUID, spec: dict[str, Any]) -> uuid.UUID:
        with self.session() as s:
            row = RecallSpecRow(recall_case_id=recall_case_id, spec=spec)
            s.add(row)
            s.commit()
            return row.id

    def upsert_recall_spec(self, *, recall_case_id: uuid.UUID, spec: dict[str, Any]) -> uuid.UUID:
        with self.session() as s:
            stmt = (
                pg_insert(RecallSpecRow)
                .values(recall_case_id=recall_case_id, spec=spec)
                .on_conflict_do_update(
                    index_elements=[RecallSpecRow.recall_case_id],
                    set_={"spec": pg_insert(RecallSpecRow).excluded.spec},
                )
                .returning(RecallSpecRow.id)
            )
            rid = s.execute(stmt).scalar_one()
            s.commit()
            return uuid.UUID(str(rid))

    def get_recall_spec(self, *, recall_case_id: uuid.UUID) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.execute(
                select(RecallSpecRow.spec).where(RecallSpecRow.recall_case_id == recall_case_id)
            ).scalar_one_or_none()
            return row if isinstance(row, dict) else None

    def insert_blast_radius_snapshot(self, *, recall_case_id: uuid.UUID, snapshot: dict[str, Any]) -> int:
        with self.session() as s:
            latest = (
                s.execute(
                    select(func.coalesce(func.max(AffectedBlastRadiusSnapshot.version), 0)).where(
                        AffectedBlastRadiusSnapshot.recall_case_id == recall_case_id
                    )
                ).scalar_one()
            )
            version = int(latest) + 1
            row = AffectedBlastRadiusSnapshot(recall_case_id=recall_case_id, version=version, snapshot=snapshot)
            s.add(row)
            s.commit()
            return version

    def get_latest_blast_radius_snapshot(self, *, recall_case_id: uuid.UUID) -> dict[str, Any] | None:
        with self.session() as s:
            row = (
                s.execute(
                    select(AffectedBlastRadiusSnapshot.snapshot)
                    .where(AffectedBlastRadiusSnapshot.recall_case_id == recall_case_id)
                    .order_by(AffectedBlastRadiusSnapshot.version.desc())
                    .limit(1)
                ).scalar_one_or_none()
            )
            return row if isinstance(row, dict) else None

    def get_scored_transaction_ids(self, *, recall_case_id: uuid.UUID) -> set[uuid.UUID]:
        with self.session() as s:
            rows = s.execute(
                select(ScoredTransaction.transaction_id).where(ScoredTransaction.recall_case_id == recall_case_id)
            ).scalars().all()
            return {uuid.UUID(str(r)) for r in rows}

    def list_scored_transactions_minimal(self, *, recall_case_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(ScoredTransaction.transaction_id, ScoredTransaction.details).where(
                    ScoredTransaction.recall_case_id == recall_case_id
                )
            ).all()
            out: list[dict[str, Any]] = []
            for tx_id, details in rows:
                out.append(
                    {
                        "transaction_id": uuid.UUID(str(tx_id)),
                        "details": details if isinstance(details, dict) else {},
                    }
                )
            out.sort(key=lambda r: str(r["transaction_id"]))
            return out

    def insert_scope_version(self, *, recall_case_id: uuid.UUID, scope: dict[str, Any]) -> int:
        with self.session() as s:
            latest = (
                s.execute(
                    select(func.coalesce(func.max(RecallScopeVersion.version), 0)).where(
                        RecallScopeVersion.recall_case_id == recall_case_id
                    )
                ).scalar_one()
            )
            version = int(latest) + 1
            row = RecallScopeVersion(recall_case_id=recall_case_id, version=version, scope=scope)
            s.add(row)
            s.commit()
            return version

    def get_latest_scope(self, *, recall_case_id: uuid.UUID) -> dict[str, Any] | None:
        with self.session() as s:
            row = (
                s.execute(
                    select(RecallScopeVersion.scope)
                    .where(RecallScopeVersion.recall_case_id == recall_case_id)
                    .order_by(RecallScopeVersion.version.desc())
                    .limit(1)
                ).scalar_one_or_none()
            )
            return row if isinstance(row, dict) else None

    def find_recall_case_by_dedupe_key(self, *, dedupe_key: str) -> uuid.UUID | None:
        with self.session() as s:
            row = s.execute(
                select(RecallCase.id).where(text("source_details->>'dedupe_key' = :k")).params(k=dedupe_key)
            ).scalar_one_or_none()
            return uuid.UUID(str(row)) if row is not None else None

    def set_recall_case_source_details(self, *, recall_case_id: uuid.UUID, source_details: dict[str, Any]) -> None:
        with self.session() as s:
            rc = s.get(RecallCase, recall_case_id)
            if rc is None:
                raise KeyError("recall_case not found")
            rc.source_details = source_details
            s.commit()

    def get_recall_case(self, recall_case_id: uuid.UUID) -> RecallCase | None:
        with self.session() as s:
            return s.get(RecallCase, recall_case_id)

    def upsert_scored_transactions(self, *, recall_case_id: uuid.UUID, scored: Iterable[Any]) -> None:
        """
        Insert or update scored transaction rows for a recall case.

        Expects each item to be either:
        - an ORM ScoredTransaction instance (transaction_id, affected_probability, details)
        - an object with `to_row(recall_case_id=...)` returning ScoredTransaction
        """
        rows: list[dict[str, Any]] = []
        for item in scored:
            row_obj: Any
            if hasattr(item, "to_row"):
                row_obj = item.to_row(recall_case_id=recall_case_id)
            else:
                row_obj = item
            tx_id = getattr(row_obj, "transaction_id", None)
            ap = getattr(row_obj, "affected_probability", None)
            details = getattr(row_obj, "details", None)
            if tx_id is None or ap is None:
                continue
            rows.append(
                {
                    "recall_case_id": recall_case_id,
                    "transaction_id": tx_id,
                    "affected_probability": int(ap),
                    "details": details if isinstance(details, dict) else {},
                }
            )
        if not rows:
            return
        with self.session() as s:
            stmt = (
                pg_insert(ScoredTransaction)
                .values(rows)
                .on_conflict_do_update(
                    constraint="uq_score_case_tx",
                    set_={
                        "affected_probability": pg_insert(ScoredTransaction).excluded.affected_probability,
                        "details": pg_insert(ScoredTransaction).excluded.details,
                    },
                )
            )
            s.execute(stmt)
            s.commit()

    def insert_notification_drafts(self, *, recall_case_id: uuid.UUID, drafts: Iterable[Any]) -> None:
        """
        Insert notification draft rows for a recall case.

        Expects each item to be either:
        - an ORM NotificationDraft instance
        - an object with `to_row(recall_case_id=...)` returning NotificationDraft

        Note: The current schema does not enforce draft idempotency (no unique constraint).
        """
        rows: list[NotificationDraft] = []
        for item in drafts:
            row_obj: Any
            if hasattr(item, "to_row"):
                row_obj = item.to_row(recall_case_id=recall_case_id)
            else:
                row_obj = item
            if not isinstance(row_obj, NotificationDraft):
                continue
            rows.append(row_obj)
        if not rows:
            return
        # Deterministic insert order reduces deadlock risk under concurrency.
        rows.sort(key=lambda r: (str(r.customer_id or ""), r.confidence_tier, r.channel))
        with self.session() as s:
            for r in rows:
                s.add(r)
            s.commit()

    def update_recall_case_state(self, recall_case_id: uuid.UUID, state: str) -> None:
        with self.session() as s:
            rc = s.get(RecallCase, recall_case_id)
            if rc is None:
                raise KeyError("recall_case not found")
            rc.state = RecallCaseState(state)
            s.commit()

    def count_employee_tasks(self, *, recall_case_id: uuid.UUID) -> int:
        with self.session() as s:
            return int(
                s.execute(select(func.count()).select_from(EmployeeTask).where(EmployeeTask.recall_case_id == recall_case_id)).scalar_one()
            )

    def count_notification_drafts(self, *, recall_case_id: uuid.UUID) -> int:
        with self.session() as s:
            return int(
                s.execute(
                    select(func.count())
                    .select_from(NotificationDraft)
                    .where(NotificationDraft.recall_case_id == recall_case_id)
                ).scalar_one()
            )

    def delete_recall_case(self, recall_case_id: uuid.UUID) -> None:
        with self.session() as s:
            rc = s.get(RecallCase, recall_case_id)
            if rc is None:
                return
            s.delete(rc)
            s.commit()
