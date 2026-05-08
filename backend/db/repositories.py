from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import Engine, Select, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.db.ctes import cte_blast_radius_from_ingredient_lot, cte_inventory_composition_at_time
from backend.db.models import (
    AffectedBlastRadiusSnapshot,
    Approval,
    ComplianceLog,
    Customer,
    Distributor,
    DistributorWarehouse,
    Facility,
    FinishedProduct,
    FinishedProductLot,
    Ingredient,
    IngredientLot,
    InstitutionalAccount,
    Manufacturer,
    NotificationDraft,
    Pallet,
    PosTransaction,
    ProductionRun,
    RecallCase,
    RecallSpecRow,
    RecallScopeVersion,
    RefrigerationEvent,
    RefrigerationZone,
    ScoredTransaction,
    Shipment,
    StockingEvent,
    Store,
    StoreShipment,
    Supplier,
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
    def create_recall_case(self) -> uuid.UUID:
        with self.session() as s:
            rc = RecallCase()
            s.add(rc)
            s.commit()
            return rc.id

    def attach_spec(self, recall_case_id: uuid.UUID, spec: dict[str, Any]) -> uuid.UUID:
        with self.session() as s:
            row = RecallSpecRow(recall_case_id=recall_case_id, spec=spec)
            s.add(row)
            s.commit()
            return row.id

    def get_recall_case(self, recall_case_id: uuid.UUID) -> RecallCase | None:
        with self.session() as s:
            return s.get(RecallCase, recall_case_id)

    def update_recall_case_state(self, recall_case_id: uuid.UUID, state: str) -> None:
        with self.session() as s:
            rc = s.get(RecallCase, recall_case_id)
            if rc is None:
                raise KeyError("recall_case not found")
            rc.state = RecallCaseState(state)
            s.commit()

    def delete_recall_case(self, recall_case_id: uuid.UUID) -> None:
        with self.session() as s:
            rc = s.get(RecallCase, recall_case_id)
            if rc is None:
                return
            s.delete(rc)
            s.commit()
