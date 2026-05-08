from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.db.ctes import cte_blast_radius_from_ingredient_lot
from backend.db.models import (
    Distributor,
    DistributorWarehouse,
    Facility,
    FinishedProduct,
    FinishedProductLot,
    Ingredient,
    IngredientLot,
    Manufacturer,
    Pallet,
    PaymentType,
    PosTransaction,
    ProductionRun,
    Shipment,
    Store,
    StoreShipment,
    Supplier,
)


def test_cte_blast_radius_from_ingredient_lot_returns_all_12(engine) -> None:
    """
    Hand-crafted 4-store scenario:
      1 ingredient lot -> 2 production runs -> 2 finished product lots -> 4 pallets
      -> 3 manufacturer shipments -> 4 store shipments -> 12 transactions.

    Definition of done: query returns all 12 transaction ids.
    """
    t0 = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as s:
        supplier = Supplier(name="Supplier BR")
        manufacturer = Manufacturer(name="Maker BR")
        distributor = Distributor(name="Distributor BR")
        s.add_all([supplier, manufacturer, distributor])
        s.flush()
        wh = DistributorWarehouse(distributor_id=distributor.id, name="WH BR", timezone="UTC")
        s.add(wh)
        s.flush()

        facility = Facility(
            manufacturer_id=manufacturer.id, name="Plant BR", plant_code="BRP", timezone="UTC"
        )
        ingredient = Ingredient(name="Ingredient BR", supplier_id=supplier.id)
        s.add_all([facility, ingredient])
        s.flush()

        ingredient_lot = IngredientLot(
            ingredient_id=ingredient.id,
            facility_id=facility.id,
            lot_code="IL-BR-1",
            received_at=t0,
            meta={},
        )
        s.add(ingredient_lot)
        s.flush()

        pr1 = ProductionRun(
            facility_id=facility.id,
            started_at=t0 + timedelta(hours=1),
            ended_at=t0 + timedelta(hours=2),
            ingredient_lots_used=[{"ingredient_lot_id": str(ingredient_lot.id), "quantity_kg": 1.0}],
        )
        pr2 = ProductionRun(
            facility_id=facility.id,
            started_at=t0 + timedelta(hours=3),
            ended_at=t0 + timedelta(hours=4),
            ingredient_lots_used=[{"ingredient_lot_id": str(ingredient_lot.id), "quantity_kg": 1.0}],
        )
        product = FinishedProduct(
            manufacturer_id=manufacturer.id,
            name="Product BR",
            upc="000000009999",
            ingredient_recipe=[{"ingredient_id": str(ingredient.id), "quantity_g": 10.0}],
        )
        s.add_all([pr1, pr2, product])
        s.flush()

        lot1 = FinishedProductLot(
            finished_product_id=product.id,
            production_run_id=pr1.id,
            lot_code="BRP-042026-A",
            produced_at=t0 + timedelta(hours=2),
            best_by_date=t0 + timedelta(days=120),
        )
        lot2 = FinishedProductLot(
            finished_product_id=product.id,
            production_run_id=pr2.id,
            lot_code="BRP-042026-B",
            produced_at=t0 + timedelta(hours=4),
            best_by_date=t0 + timedelta(days=120),
        )
        s.add_all([lot1, lot2])
        s.flush()

        # 3 shipments (manufacturer -> distributor)
        sh1 = Shipment(manufacturer_id=manufacturer.id, distributor_id=distributor.id, shipped_at=t0)
        sh2 = Shipment(manufacturer_id=manufacturer.id, distributor_id=distributor.id, shipped_at=t0)
        sh3 = Shipment(manufacturer_id=manufacturer.id, distributor_id=distributor.id, shipped_at=t0)
        s.add_all([sh1, sh2, sh3])
        s.flush()

        stores = [Store(name=f"Store BR {i+1}", timezone="UTC") for i in range(4)]
        s.add_all(stores)
        s.flush()

        # Store shipments: split pallets across 4 stores
        store_shipments = []
        for idx, st in enumerate(stores):
            ss = StoreShipment(
                warehouse_id=wh.id,
                store_id=st.id,
                shipped_at=t0 + timedelta(days=1),
                arrived_at=t0 + timedelta(days=1, hours=1),
            )
            store_shipments.append(ss)
        s.add_all(store_shipments)
        s.flush()

        pallets = [
            Pallet(finished_product_lot_id=lot1.id, shipment_id=sh1.id, store_shipment_id=store_shipments[0].id, units_total=50),
            Pallet(finished_product_lot_id=lot1.id, shipment_id=sh2.id, store_shipment_id=store_shipments[1].id, units_total=50),
            Pallet(finished_product_lot_id=lot2.id, shipment_id=sh3.id, store_shipment_id=store_shipments[2].id, units_total=50),
            Pallet(finished_product_lot_id=lot2.id, shipment_id=sh3.id, store_shipment_id=store_shipments[3].id, units_total=50),
        ]
        s.add_all(pallets)
        s.flush()

        # 12 transactions (3 per store) after shipments
        txs = []
        for st in stores:
            for j in range(3):
                txs.append(
                    PosTransaction(
                        store_id=st.id,
                        customer_id=None,
                        timestamp=t0 + timedelta(days=2, hours=j),
                        payment_type=PaymentType.cash,
                        line_items=[{"finished_product_id": str(product.id), "quantity_units": 1}],
                    )
                )
        s.add_all(txs)
        s.commit()

        rows = s.execute(cte_blast_radius_from_ingredient_lot(), {"ingredient_lot_id": ingredient_lot.id}).all()
        got = {r[0] for r in rows}
        expected = {tx.id for tx in txs}
        assert got == expected
