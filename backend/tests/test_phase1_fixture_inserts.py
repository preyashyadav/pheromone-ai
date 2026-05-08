from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

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
    PaymentType,
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
)


def test_fixture_inserts_one_row_each_table(engine) -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as s:
        supplier = Supplier(name="Supplier X")
        manufacturer = Manufacturer(name="Manufacturer X")
        distributor = Distributor(name="Distributor X")
        store = Store(name="Store X")
        s.add_all([supplier, manufacturer, distributor, store])
        s.flush()

        ingredient = Ingredient(name="Ingredient X", supplier_id=supplier.id)
        facility = Facility(
            manufacturer_id=manufacturer.id, name="Plant X", plant_code="PX", timezone="UTC"
        )
        s.add_all([ingredient, facility])
        s.flush()

        ingredient_lot = IngredientLot(
            ingredient_id=ingredient.id,
            facility_id=facility.id,
            lot_code="IL-X",
            received_at=now,
            meta={},
        )
        s.add(ingredient_lot)
        s.flush()

        production_run = ProductionRun(
            facility_id=facility.id,
            started_at=now,
            ended_at=now,
            ingredient_lots_used=[{"ingredient_lot_id": str(ingredient_lot.id), "quantity_kg": 1.0}],
        )
        finished_product = FinishedProduct(
            manufacturer_id=manufacturer.id,
            name="Product X",
            upc="000000000123",
            ingredient_recipe=[{"ingredient_id": str(ingredient.id), "quantity_g": 10.0}],
        )
        s.add_all([production_run, finished_product])
        s.flush()

        fpl = FinishedProductLot(
            finished_product_id=finished_product.id,
            production_run_id=production_run.id,
            lot_code="PX-050126-A",
            produced_at=now,
            best_by_date=now,
        )
        shipment = Shipment(
            manufacturer_id=manufacturer.id, distributor_id=distributor.id, shipped_at=now
        )
        wh = DistributorWarehouse(distributor_id=distributor.id, name="WH X", timezone="UTC")
        s.add_all([fpl, shipment, wh])
        s.flush()

        ss = StoreShipment(warehouse_id=wh.id, store_id=store.id, shipped_at=now)
        s.add(ss)
        s.flush()

        pallet = Pallet(
            finished_product_lot_id=fpl.id,
            shipment_id=shipment.id,
            store_shipment_id=ss.id,
            units_total=100,
        )
        s.add(pallet)
        s.flush()

        stock = StockingEvent(
            store_id=store.id,
            pallet_id=pallet.id,
            finished_product_id=finished_product.id,
            timestamp=now,
            units_added=10,
        )
        customer = Customer(profile={"language": "en", "kids_at_home": False, "allergies": []})
        s.add_all([stock, customer])
        s.flush()

        inst = InstitutionalAccount(account_type="school", name="School X", customer_id=customer.id)
        tx = PosTransaction(
            store_id=store.id,
            customer_id=customer.id,
            timestamp=now,
            payment_type=PaymentType.loyalty,
            line_items=[
                {"finished_product_id": str(finished_product.id), "quantity_units": 1, "finished_product_lot_id": str(fpl.id)}
            ],
        )
        s.add_all([inst, tx])
        s.flush()

        zone = RefrigerationZone(store_id=store.id, name="Zone X")
        s.add(zone)
        s.flush()

        rz_evt = RefrigerationEvent(zone_id=zone.id, event_type="inspection", timestamp=now, details={})
        s.add(rz_evt)
        s.flush()

        recall = RecallCase()
        s.add(recall)
        s.flush()

        spec = RecallSpecRow(recall_case_id=recall.id, spec={"title": "Recall X"})
        scope = RecallScopeVersion(recall_case_id=recall.id, version=1, scope={"kind": "test"})
        blast = AffectedBlastRadiusSnapshot(recall_case_id=recall.id, version=1, snapshot={"stores": []})
        scored = ScoredTransaction(recall_case_id=recall.id, transaction_id=tx.id, affected_probability=0, details={})
        task_payload = {"op": "hold"}
        from backend.db.models import EmployeeTask

        task = EmployeeTask(recall_case_id=recall.id, task_type="pull", payload=task_payload, status="open")
        draft = NotificationDraft(
            recall_case_id=recall.id, customer_id=customer.id, channel="email", confidence_tier="confirmed_unaffected", draft={"body": "ok"}
        )
        approval = Approval(recall_case_id=recall.id, approved_by="mgr", action="approve")
        log = ComplianceLog(recall_case_id=recall.id, event_type="test", message="event", payload={})
        s.add_all([spec, scope, blast, scored, task, draft, approval, log])

        s.commit()
