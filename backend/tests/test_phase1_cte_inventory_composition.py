from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.db.ctes import cte_inventory_composition_at_time
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
    StockingEvent,
    Store,
    StoreShipment,
    Supplier,
)


def test_cte_inventory_composition_at_time_probability_distribution(engine) -> None:
    """
    Fixture:
      - 2 pallets (A, B)
      - 3 stocking events (A:10, B:10, A:+5)
      - 5 sale events totaling 8 units

    FIFO consumption should leave:
      - Pallet A: 15 - 8 = 7
      - Pallet B: 10
      => probabilities: A=7/17, B=10/17
    """
    t0 = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    with Session(engine) as s:
        supplier = Supplier(name="Supplier IC")
        manufacturer = Manufacturer(name="Maker IC")
        distributor = Distributor(name="Distributor IC")
        s.add_all([supplier, manufacturer, distributor])
        s.flush()
        wh = DistributorWarehouse(distributor_id=distributor.id, name="WH IC", timezone="UTC")
        s.add(wh)
        s.flush()

        facility = Facility(
            manufacturer_id=manufacturer.id, name="Plant IC", plant_code="ICP", timezone="UTC"
        )
        ingredient = Ingredient(name="Ingredient IC", supplier_id=supplier.id)
        s.add_all([facility, ingredient])
        s.flush()

        ingredient_lot = IngredientLot(
            ingredient_id=ingredient.id, facility_id=facility.id, lot_code="IL-IC-1", received_at=t0, meta={}
        )
        s.add(ingredient_lot)
        s.flush()

        pr = ProductionRun(
            facility_id=facility.id,
            started_at=t0,
            ended_at=t0,
            ingredient_lots_used=[{"ingredient_lot_id": str(ingredient_lot.id), "quantity_kg": 1.0}],
        )
        product = FinishedProduct(
            manufacturer_id=manufacturer.id,
            name="Product IC",
            upc="000000001111",
            ingredient_recipe=[{"ingredient_id": str(ingredient.id), "quantity_g": 10.0}],
        )
        s.add_all([pr, product])
        s.flush()

        lot = FinishedProductLot(
            finished_product_id=product.id,
            production_run_id=pr.id,
            lot_code="ICP-040126-A",
            produced_at=t0,
            best_by_date=t0 + timedelta(days=100),
        )
        store = Store(name="Store IC", timezone="UTC")
        s.add_all([lot, store])
        s.flush()

        ss = StoreShipment(warehouse_id=wh.id, store_id=store.id, shipped_at=t0)
        s.add(ss)
        s.flush()

        pallet_a = Pallet(finished_product_lot_id=lot.id, shipment_id=None, store_shipment_id=ss.id, units_total=100)
        pallet_b = Pallet(finished_product_lot_id=lot.id, shipment_id=None, store_shipment_id=ss.id, units_total=100)
        s.add_all([pallet_a, pallet_b])
        s.flush()

        se1 = StockingEvent(store_id=store.id, pallet_id=pallet_a.id, finished_product_id=product.id, timestamp=t0 + timedelta(hours=1), units_added=10)
        se2 = StockingEvent(store_id=store.id, pallet_id=pallet_b.id, finished_product_id=product.id, timestamp=t0 + timedelta(hours=2), units_added=10)
        se3 = StockingEvent(store_id=store.id, pallet_id=pallet_a.id, finished_product_id=product.id, timestamp=t0 + timedelta(hours=3), units_added=5)
        s.add_all([se1, se2, se3])
        s.flush()

        # 5 sale events; total sold 8 units.
        sale_times = [t0 + timedelta(hours=1, minutes=30 + i) for i in range(5)]
        sold_units = [2, 2, 2, 1, 1]
        txs = []
        for tm, qty in zip(sale_times, sold_units, strict=True):
            txs.append(
                PosTransaction(
                    store_id=store.id,
                    customer_id=None,
                    timestamp=tm,
                    payment_type=PaymentType.cash,
                    line_items=[{"finished_product_id": str(product.id), "quantity_units": qty}],
                )
            )
        s.add_all(txs)
        s.commit()

        rows = s.execute(
            cte_inventory_composition_at_time(),
            {"store_id": store.id, "finished_product_id": product.id, "as_of": t0 + timedelta(hours=4)},
        ).all()
        got = {r[0]: float(r[1]) for r in rows if float(r[1]) > 0}
        assert set(got.keys()) == {pallet_a.id, pallet_b.id}
        assert abs(got[pallet_a.id] - (7 / 17)) < 1e-6
        assert abs(got[pallet_b.id] - (10 / 17)) < 1e-6
