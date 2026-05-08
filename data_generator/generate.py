from __future__ import annotations

import sys
import argparse
import os
import random
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import json
from pathlib import Path

from faker import Faker
from sqlalchemy import Engine, create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.db.models import ContaminationStatus, PaymentType  # noqa: E402
from data_generator.seeds import salsa_verde_seed, store4_fridge_seed


SCENARIOS = {"salsa_verde", "store4_fridge", "both", "none"}


def _dt(day: int) -> datetime:
    return datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc) + timedelta(days=day)


def det_uuid(*parts: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, "|".join(parts))


def connect(db_url: str) -> Engine:
    return create_engine(db_url, pool_pre_ping=True)


def reset_all_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                """
            )
        ).scalars().all()
        if not tables:
            return
        conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE;"))


def insert_many(engine: Engine, sql: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    prepped: list[dict[str, Any]] = []
    for row in rows:
        out: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, (dict, list)):
                out[k] = json.dumps(v)
            else:
                out[k] = v
        prepped.append(out)
    with engine.begin() as conn:
        conn.execute(text(sql), prepped)


@dataclass(frozen=True)
class StaticIds:
    suppliers: dict[str, uuid.UUID]
    ingredients: dict[str, uuid.UUID]
    manufacturers: dict[str, uuid.UUID]
    facilities: dict[str, uuid.UUID]
    distributors: dict[str, uuid.UUID]
    warehouses: dict[str, uuid.UUID]
    stores: dict[str, uuid.UUID]
    finished_products: dict[str, uuid.UUID]  # keyed by upc


def generate_static_seeds(engine: Engine, seed: int) -> StaticIds:
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)

    suppliers = {f"Supplier {i}": det_uuid("supplier", str(i)) for i in range(1, 9)}
    insert_many(
        engine,
        """
        INSERT INTO suppliers (id, name)
        VALUES (:id, :name)
        ON CONFLICT DO NOTHING
        """,
        [{"id": sid, "name": name} for name, sid in suppliers.items()],
    )

    # Ingredients: include required named ones; fill to 35.
    base_ingredients = [
        "salt",
        "garlic_powder",
        "paprika",
        salsa_verde_seed.INGREDIENT_NAME,
        "cilantro",
        "tomato_paste",
        "lime_juice",
        "vinegar",
        "onion_powder",
        "cumin",
        "oregano",
    ]
    # Total ingredients should be 35 including the composite seasoning blend.
    while len(base_ingredients) < 34:
        base_ingredients.append(f"ingredient_{len(base_ingredients)+1}")

    seasoning_blend = "seasoning_blend_X"
    ingredient_ids = {name: det_uuid("ingredient", name) for name in base_ingredients + [seasoning_blend]}
    # Make 5 hierarchical children under seasoning_blend_X
    children = ["salt", "garlic_powder", "paprika", salsa_verde_seed.INGREDIENT_NAME]
    ingredient_sql = """
        INSERT INTO ingredients (id, supplier_id, parent_ingredient_id, name)
        VALUES (:id, :supplier_id, :parent_ingredient_id, :name)
        ON CONFLICT DO NOTHING
    """
    # Insert the composite parent first to satisfy FK constraints.
    insert_many(
        engine,
        ingredient_sql,
        [
            {
                "id": ingredient_ids[seasoning_blend],
                "supplier_id": suppliers[rng.choice(list(suppliers.keys()))],
                "parent_ingredient_id": None,
                "name": seasoning_blend,
            }
        ],
    )
    ingredient_rows = []
    for name, iid in ingredient_ids.items():
        if name == seasoning_blend:
            continue
        supplier_name = rng.choice(list(suppliers.keys()))
        parent_id = ingredient_ids[seasoning_blend] if name in children else None
        ingredient_rows.append(
            {
                "id": iid,
                "supplier_id": suppliers[supplier_name],
                "parent_ingredient_id": parent_id,
                "name": name,
            }
        )
    insert_many(engine, ingredient_sql, ingredient_rows)

    manufacturers = {
        salsa_verde_seed.MANUFACTURER_NAME: det_uuid("manufacturer", salsa_verde_seed.MANUFACTURER_NAME),
        "Acme Kitchens": det_uuid("manufacturer", "Acme Kitchens"),
        "NorthStar Foods": det_uuid("manufacturer", "NorthStar Foods"),
        "GreenField Co": det_uuid("manufacturer", "GreenField Co"),
    }
    insert_many(
        engine,
        """
        INSERT INTO manufacturers (id, name)
        VALUES (:id, :name)
        ON CONFLICT DO NOTHING
        """,
        [{"id": mid, "name": name} for name, mid in manufacturers.items()],
    )

    # 8 facilities, with Sunny Valley having 3 plants including Plant 2 (code P2).
    facilities: dict[str, uuid.UUID] = {}
    facility_rows: list[dict[str, Any]] = []
    facility_specs = [
        (salsa_verde_seed.MANUFACTURER_NAME, "Sunny Valley Plant 1", "P1"),
        (salsa_verde_seed.MANUFACTURER_NAME, "Sunny Valley Plant 2", salsa_verde_seed.PLANT_CODE),
        (salsa_verde_seed.MANUFACTURER_NAME, "Sunny Valley Plant 3", "P3"),
        ("Acme Kitchens", "Acme Plant 1", "A1"),
        ("Acme Kitchens", "Acme Plant 2", "A2"),
        ("NorthStar Foods", "NorthStar Plant 1", "N1"),
        ("NorthStar Foods", "NorthStar Plant 2", "N2"),
        ("GreenField Co", "GreenField Plant 1", "G1"),
    ]
    for mname, fname, plant_code in facility_specs:
        fid = det_uuid("facility", plant_code)
        facilities[plant_code] = fid
        facility_rows.append(
            {
                "id": fid,
                "manufacturer_id": manufacturers[mname],
                "name": fname,
                "plant_code": plant_code,
                "timezone": "UTC",
            }
        )
    insert_many(
        engine,
        """
        INSERT INTO facilities (id, manufacturer_id, name, plant_code, timezone)
        VALUES (:id, :manufacturer_id, :name, :plant_code, :timezone)
        ON CONFLICT DO NOTHING
        """,
        facility_rows,
    )

    distributors = {
        salsa_verde_seed.DIST_NAME: det_uuid("distributor", salsa_verde_seed.DIST_NAME),
        "Distributor East": det_uuid("distributor", "Distributor East"),
    }
    insert_many(
        engine,
        """
        INSERT INTO distributors (id, name)
        VALUES (:id, :name)
        ON CONFLICT DO NOTHING
        """,
        [{"id": did, "name": name} for name, did in distributors.items()],
    )

    # 4 warehouses (2 per distributor).
    warehouses: dict[str, uuid.UUID] = {}
    wh_rows: list[dict[str, Any]] = []
    wh_specs = [
        (salsa_verde_seed.DIST_NAME, "West Warehouse 1", "W1"),
        (salsa_verde_seed.DIST_NAME, "West Warehouse 2", "W2"),
        ("Distributor East", "East Warehouse 1", "E1"),
        ("Distributor East", "East Warehouse 2", "E2"),
    ]
    for dname, wh_name, code in wh_specs:
        wid = det_uuid("warehouse", code)
        warehouses[code] = wid
        wh_rows.append(
            {
                "id": wid,
                "distributor_id": distributors[dname],
                "name": wh_name,
                "timezone": "UTC",
            }
        )
    insert_many(
        engine,
        """
        INSERT INTO distributor_warehouses (id, distributor_id, name, timezone)
        VALUES (:id, :distributor_id, :name, :timezone)
        ON CONFLICT DO NOTHING
        """,
        wh_rows,
    )

    stores = {name: det_uuid("store", name) for name in salsa_verde_seed.ACME_STORE_NAMES}
    insert_many(
        engine,
        """
        INSERT INTO stores (id, name, timezone)
        VALUES (:id, :name, :timezone)
        ON CONFLICT DO NOTHING
        """,
        [{"id": sid, "name": name, "timezone": "America/Los_Angeles"} for name, sid in stores.items()],
    )

    # 60 finished products. Ensure Salsa Verde product exists.
    upcs: list[str] = [salsa_verde_seed.FINISHED_PRODUCT_UPC]
    while len(upcs) < 60:
        upcs.append(f"{rng.randrange(10**11, 10**12):012d}")

    finished_products: dict[str, uuid.UUID] = {upc: det_uuid("product", upc) for upc in upcs}
    product_rows: list[dict[str, Any]] = []
    blend_used = 0
    for upc in upcs:
        if upc == salsa_verde_seed.FINISHED_PRODUCT_UPC:
            name = salsa_verde_seed.FINISHED_PRODUCT_NAME
            manufacturer_id = manufacturers[salsa_verde_seed.MANUFACTURER_NAME]
            recipe = [
                {"ingredient_id": str(ingredient_ids[salsa_verde_seed.INGREDIENT_NAME]), "quantity_g": 20.0},
                {"ingredient_id": str(ingredient_ids["salt"]), "quantity_g": 2.0},
                {"ingredient_id": str(ingredient_ids["cilantro"]), "quantity_g": 5.0},
            ]
        else:
            name = f"{fake.company()} Item {upc[-4:]}"
            manufacturer_id = manufacturers[rng.choice(list(manufacturers.keys()))]
            # At least 5 finished products use seasoning_blend_X in their recipe.
            recipe = []
            if blend_used < 5:
                recipe.append({"ingredient_id": str(ingredient_ids[seasoning_blend]), "quantity_g": 3.0})
                blend_used += 1
            for _ in range(3):
                ing = rng.choice(base_ingredients)
                recipe.append({"ingredient_id": str(ingredient_ids[ing]), "quantity_g": float(rng.randint(1, 30))})
        product_rows.append(
            {"id": finished_products[upc], "manufacturer_id": manufacturer_id, "name": name, "upc": upc, "ingredient_recipe": recipe}
        )
    insert_many(
        engine,
        """
        INSERT INTO finished_products (id, manufacturer_id, name, upc, ingredient_recipe)
        VALUES (:id, :manufacturer_id, :name, :upc, CAST(:ingredient_recipe AS jsonb))
        ON CONFLICT DO NOTHING
        """,
        product_rows,
    )

    return StaticIds(
        suppliers=suppliers,
        ingredients=ingredient_ids,
        manufacturers=manufacturers,
        facilities=facilities,
        distributors=distributors,
        warehouses=warehouses,
        stores=stores,
        finished_products=finished_products,
    )


def generate_time_series(engine: Engine, ids: StaticIds, seed: int, scenario: str) -> dict[str, int]:
    rng = random.Random(seed)

    # 300 ingredient lots across facilities, over 60 days.
    ingredient_lot_rows: list[dict[str, Any]] = []
    lot_codes = []
    for i in range(300):
        ing_name = rng.choice(list(ids.ingredients.keys()))
        plant_code = rng.choice(list(ids.facilities.keys()))
        lot_code = f"IL-{plant_code}-{i:04d}"
        lot_codes.append(lot_code)
        ingredient_lot_rows.append(
            {
                "id": det_uuid("ingredient_lot", lot_code),
                "ingredient_id": ids.ingredients[ing_name],
                "facility_id": ids.facilities[plant_code],
                "lot_code": lot_code,
                "received_at": _dt(rng.randrange(0, 60)),
                "contamination_status": ContaminationStatus.unknown.value,
                "metadata": {},
            }
        )

    # Inject Salsa-Verde RG-4429 exact lot.
    if scenario in {"salsa_verde", "both"}:
        ingredient_lot_rows.append(
            {
                "id": det_uuid("ingredient_lot", salsa_verde_seed.INGREDIENT_LOT_CODE),
                "ingredient_id": ids.ingredients[salsa_verde_seed.INGREDIENT_NAME],
                "facility_id": ids.facilities[salsa_verde_seed.PLANT_CODE],
                "lot_code": salsa_verde_seed.INGREDIENT_LOT_CODE,
                "received_at": salsa_verde_seed.RG4429_WINDOW_START_UTC + timedelta(days=1),
                "contamination_status": ContaminationStatus.confirmed_contaminated.value,
                "metadata": {"scenario": "salsa_verde"},
            }
        )

    insert_many(
        engine,
        """
        INSERT INTO ingredient_lots (id, ingredient_id, facility_id, lot_code, received_at, contamination_status, metadata)
        VALUES (:id, :ingredient_id, :facility_id, :lot_code, :received_at, :contamination_status, CAST(:metadata AS jsonb))
        ON CONFLICT DO NOTHING
        """,
        ingredient_lot_rows,
    )

    # 500 production runs, each uses 1-3 ingredient lots.
    production_run_rows: list[dict[str, Any]] = []
    pr_ids: list[uuid.UUID] = []
    for i in range(500):
        plant_code = rng.choice(list(ids.facilities.keys()))
        started = _dt(rng.randrange(0, 60)) + timedelta(hours=rng.randrange(0, 24))
        ended = started + timedelta(hours=2)
        used = []
        for _ in range(rng.randint(1, 3)):
            lot_code = rng.choice(lot_codes)
            used.append({"ingredient_lot_id": str(det_uuid("ingredient_lot", lot_code)), "quantity_kg": float(rng.randint(1, 50))})
        pr_id = det_uuid("production_run", str(i), plant_code)
        pr_ids.append(pr_id)
        production_run_rows.append(
            {
                "id": pr_id,
                "facility_id": ids.facilities[plant_code],
                "started_at": started,
                "ended_at": ended,
                "ingredient_lots_used": used,
            }
        )

    # Inject 6 seeded production runs at Plant 2 using RG-4429 only.
    seeded_pr_ids: list[uuid.UUID] = []
    if scenario in {"salsa_verde", "both"}:
        for idx, lot_code in enumerate(salsa_verde_seed.PRODUCT_LOT_CODES):
            started = datetime(2026, 5, 21, 8 + idx, 0, tzinfo=timezone.utc)
            pr_id = det_uuid("production_run", "salsa", lot_code)
            seeded_pr_ids.append(pr_id)
            production_run_rows.append(
                {
                    "id": pr_id,
                    "facility_id": ids.facilities[salsa_verde_seed.PLANT_CODE],
                    "started_at": started,
                    "ended_at": started + timedelta(hours=2),
                    "ingredient_lots_used": [
                        {"ingredient_lot_id": str(det_uuid("ingredient_lot", salsa_verde_seed.INGREDIENT_LOT_CODE)), "quantity_kg": 20.0}
                    ],
                }
            )

    insert_many(
        engine,
        """
        INSERT INTO production_runs (id, facility_id, started_at, ended_at, ingredient_lots_used)
        VALUES (:id, :facility_id, :started_at, :ended_at, CAST(:ingredient_lots_used AS jsonb))
        ON CONFLICT DO NOTHING
        """,
        production_run_rows,
    )

    # 1,500 finished product lots. Tie to production runs.
    finished_product_lot_rows: list[dict[str, Any]] = []
    fpl_codes: list[str] = []
    plant_codes = list(ids.facilities.keys())
    product_upcs = list(ids.finished_products.keys())
    # Deterministic, collision-free mapping (plant_code x day x batch_letter).
    for i in range(1500):
        upc = rng.choice(product_upcs)
        plant_code = plant_codes[i % len(plant_codes)]
        day = (i // len(plant_codes)) % 60
        mmddyy = _dt(day).strftime("%m%d%y")
        batch = chr(ord("A") + ((i // (len(plant_codes) * 60)) % 26))
        lot_code = f"{plant_code}-{mmddyy}-{batch}"
        fpl_codes.append(lot_code)
        produced_at = _dt(day)
        finished_product_lot_rows.append(
            {
                "id": det_uuid("fpl", lot_code),
                "finished_product_id": ids.finished_products[upc],
                "production_run_id": rng.choice(pr_ids),
                "lot_code": lot_code,
                "produced_at": produced_at,
                "best_by_date": produced_at + timedelta(days=rng.randint(60, 180)),
            }
        )

    # Inject seeded lots P2-052126-A..F for Salsa Verde.
    if scenario in {"salsa_verde", "both"}:
        for pr_id, lot_code in zip(seeded_pr_ids, salsa_verde_seed.PRODUCT_LOT_CODES, strict=True):
            produced_at = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)
            finished_product_lot_rows.append(
                {
                    "id": det_uuid("fpl", lot_code),
                    "finished_product_id": ids.finished_products[salsa_verde_seed.FINISHED_PRODUCT_UPC],
                    "production_run_id": pr_id,
                    "lot_code": lot_code,
                    "produced_at": produced_at,
                    "best_by_date": produced_at + timedelta(days=120),
                }
            )
            fpl_codes.append(lot_code)

    insert_many(
        engine,
        """
        INSERT INTO finished_product_lots (id, finished_product_id, production_run_id, lot_code, produced_at, best_by_date)
        VALUES (:id, :finished_product_id, :production_run_id, :lot_code, :produced_at, :best_by_date)
        ON CONFLICT DO NOTHING
        """,
        finished_product_lot_rows,
    )

    # 700 manufacturer->distributor shipments
    manufacturer_ids = list(ids.manufacturers.values())
    distributor_ids = list(ids.distributors.values())
    shipment_rows: list[dict[str, Any]] = []
    shipment_ids: list[uuid.UUID] = []
    for i in range(700):
        shipped_at = _dt(rng.randrange(0, 60))
        sid = det_uuid("shipment", str(i))
        shipment_ids.append(sid)
        shipment_rows.append(
            {
                "id": sid,
                "manufacturer_id": rng.choice(manufacturer_ids),
                "distributor_id": rng.choice(distributor_ids),
                "shipped_at": shipped_at,
                "arrived_at": shipped_at + timedelta(days=1),
            }
        )

    # Seed deterministic shipments for Salsa-Verde pallets.
    if scenario in {"salsa_verde", "both"}:
        for idx in range(len(salsa_verde_seed.PRODUCT_LOT_CODES)):
            shipped_at = salsa_verde_seed.SHIP_WINDOW_START_UTC + timedelta(days=idx)
            shipment_rows.append(
                {
                    "id": det_uuid("shipment", f"salsa-{idx}"),
                    "manufacturer_id": ids.manufacturers[salsa_verde_seed.MANUFACTURER_NAME],
                    "distributor_id": ids.distributors[salsa_verde_seed.DIST_NAME],
                    "shipped_at": shipped_at,
                    "arrived_at": shipped_at + timedelta(days=1),
                }
            )
            shipment_ids.append(det_uuid("shipment", f"salsa-{idx}"))
    insert_many(
        engine,
        """
        INSERT INTO shipments (id, manufacturer_id, distributor_id, shipped_at, arrived_at)
        VALUES (:id, :manufacturer_id, :distributor_id, :shipped_at, :arrived_at)
        ON CONFLICT DO NOTHING
        """,
        shipment_rows,
    )

    # 3,000 distributor->store shipments
    store_shipment_rows: list[dict[str, Any]] = []
    store_shipment_ids: list[uuid.UUID] = []
    warehouse_ids = list(ids.warehouses.values())
    store_ids = list(ids.stores.values())
    for i in range(3000):
        shipped_at = _dt(rng.randrange(0, 60))
        ssid = det_uuid("store_shipment", str(i))
        store_shipment_ids.append(ssid)
        store_shipment_rows.append(
            {
                "id": ssid,
                "warehouse_id": rng.choice(warehouse_ids),
                "store_id": rng.choice(store_ids),
                "shipped_at": shipped_at,
                "arrived_at": shipped_at + timedelta(hours=6),
            }
        )

    # Inject seeded store shipments from Distributor West to exactly 6 stores in window.
    seeded_store_shipment_ids: list[uuid.UUID] = []
    if scenario in {"salsa_verde", "both"}:
        west_wh = ids.warehouses["W1"]
        for idx, store_name in enumerate(salsa_verde_seed.ACME_AFFECTED_STORE_NAMES):
            ssid = det_uuid("store_shipment", "salsa", store_name)
            seeded_store_shipment_ids.append(ssid)
            shipped_at = salsa_verde_seed.SHIP_WINDOW_START_UTC + timedelta(days=idx)
            store_shipment_rows.append(
                {
                    "id": ssid,
                    "warehouse_id": west_wh,
                    "store_id": ids.stores[store_name],
                    "shipped_at": shipped_at,
                    "arrived_at": shipped_at + timedelta(hours=6),
                }
            )

    insert_many(
        engine,
        """
        INSERT INTO store_shipments (id, warehouse_id, store_id, shipped_at, arrived_at)
        VALUES (:id, :warehouse_id, :store_id, :shipped_at, :arrived_at)
        ON CONFLICT DO NOTHING
        """,
        store_shipment_rows,
    )

    # 8,000 pallets - tie to finished product lots and store shipments.
    pallet_rows: list[dict[str, Any]] = []
    pallet_ids: list[uuid.UUID] = []
    random_fpl_codes = (
        [c for c in fpl_codes if c not in set(salsa_verde_seed.PRODUCT_LOT_CODES)]
        if scenario in {"salsa_verde", "both"}
        else fpl_codes
    )
    for i in range(8000):
        lot_code = rng.choice(random_fpl_codes)
        pid = det_uuid("pallet", str(i))
        pallet_ids.append(pid)
        pallet_rows.append(
            {
                "id": pid,
                "finished_product_lot_id": det_uuid("fpl", lot_code),
                "shipment_id": rng.choice(shipment_ids),
                "store_shipment_id": rng.choice(store_shipment_ids),
                "units_total": rng.randint(6, 48),
            }
        )

    # Seed pallets for Salsa Verde: ensure they are shipped only to the 6 affected stores.
    seeded_pallet_ids: list[uuid.UUID] = []
    if scenario in {"salsa_verde", "both"}:
        for idx, lot_code in enumerate(salsa_verde_seed.PRODUCT_LOT_CODES):
            for k in range(20):  # 120 seeded pallets total
                pid = det_uuid("pallet", "salsa", lot_code, str(k))
                seeded_pallet_ids.append(pid)
                pallet_rows.append(
                    {
                        "id": pid,
                        "finished_product_lot_id": det_uuid("fpl", lot_code),
                        "shipment_id": det_uuid("shipment", f"salsa-{idx}"),
                        "store_shipment_id": seeded_store_shipment_ids[k % len(seeded_store_shipment_ids)],
                        "units_total": 24,
                    }
                )

    insert_many(
        engine,
        """
        INSERT INTO pallets (id, finished_product_lot_id, shipment_id, store_shipment_id, units_total)
        VALUES (:id, :finished_product_lot_id, :shipment_id, :store_shipment_id, :units_total)
        ON CONFLICT DO NOTHING
        """,
        pallet_rows,
    )

    # 6,000+ stocking events: 1 per pallet minimum, plus some split stocking events.
    stocking_rows: list[dict[str, Any]] = []
    for i, pid in enumerate(pallet_ids[:6000]):
        # derive store from store_shipment
        ssid = store_shipment_ids[i % len(store_shipment_ids)]
        stocking_rows.append(
            {
                "id": det_uuid("stock", str(i)),
                "store_id": None,  # filled via subquery insert below not supported; fill by reading mapping
            }
        )

    # We'll do stocking events via join query for performance.
    with engine.begin() as conn:
        # Create stocking events for first 6000 pallets.
        conn.execute(
            text(
                """
                INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added)
                SELECT
                  gen_random_uuid(),
                  ss.store_id,
                  p.id,
                  fpl.finished_product_id,
                  ss.arrived_at + interval '1 hour',
                  LEAST(p.units_total, 24)
                FROM pallets p
                JOIN store_shipments ss ON ss.id = p.store_shipment_id
                JOIN finished_product_lots fpl ON fpl.id = p.finished_product_lot_id
                WHERE p.id IN (
                  SELECT id FROM pallets ORDER BY created_at NULLS LAST, id LIMIT 6000
                )
                ON CONFLICT DO NOTHING
                """
            )
        )

        # Add extra split events for 500 pallets
        conn.execute(
            text(
                """
                INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added)
                SELECT
                  gen_random_uuid(),
                  ss.store_id,
                  p.id,
                  fpl.finished_product_id,
                  ss.arrived_at + interval '2 hours',
                  GREATEST(1, LEAST(p.units_total - 1, 10))
                FROM pallets p
                JOIN store_shipments ss ON ss.id = p.store_shipment_id
                JOIN finished_product_lots fpl ON fpl.id = p.finished_product_lot_id
                WHERE p.id IN (
                  SELECT id FROM pallets ORDER BY id LIMIT 500
                )
                ON CONFLICT DO NOTHING
                """
            )
        )

    return {
        "ingredient_lots": len(ingredient_lot_rows),
        "production_runs": len(production_run_rows),
        "finished_product_lots": len(finished_product_lot_rows),
        "shipments": len(shipment_rows),
        "store_shipments": len(store_shipment_rows),
        "pallets": len(pallet_rows),
        "stocking_events": 6500,
    }


def generate_customers_and_transactions(
    engine: Engine, ids: StaticIds, seed: int, scenario: str
) -> dict[str, int]:
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed + 1)

    store_ids = list(ids.stores.values())
    upcs = list(ids.finished_products.keys())

    customer_rows: list[dict[str, Any]] = []
    customer_ids: list[uuid.UUID] = []
    for i in range(2000):
        cid = det_uuid("customer", str(i))
        customer_ids.append(cid)
        preferred_store = store_ids[i % len(store_ids)]
        frequent_upcs = rng.sample(upcs, k=10)
        profile = {
            "preferred_store_id": str(preferred_store),
            "typical_weekdays": [0, 2, 5],
            "frequent_upcs": frequent_upcs,
            "language": rng.choice(["en", "es"]),
            "kids_at_home": rng.random() < 0.35,
            "immunocompromised": rng.random() < 0.08,
            "allergies": [],
            "consent_sms": rng.random() < 0.5,
            "consent_email": rng.random() < 0.7,
        }
        customer_rows.append(
            {
                "id": cid,
                "loyalty_id": f"L{100000+i}" if rng.random() < 0.5 else None,
                "email_hash": f"emailhash_{i}" if rng.random() < 0.25 else None,
                "phone_hash": f"phonehash_{i}" if rng.random() < 0.5 else None,
                "profile": profile,
            }
        )

    insert_many(
        engine,
        """
        INSERT INTO customers (id, loyalty_id, email_hash, phone_hash, profile)
        VALUES (:id, :loyalty_id, :email_hash, :phone_hash, CAST(:profile AS jsonb))
        ON CONFLICT DO NOTHING
        """,
        customer_rows,
    )

    # 15 institutional accounts, linked to first 15 customers.
    inst_rows = []
    types = ["school"] * 5 + ["hospital"] * 5 + ["restaurant"] * 5
    for i, t in enumerate(types):
        inst_rows.append(
            {
                "id": det_uuid("inst", str(i)),
                "account_type": t,
                "name": f"{t.title()} {i+1}",
                "customer_id": customer_ids[i],
            }
        )
    insert_many(
        engine,
        """
        INSERT INTO institutional_accounts (id, account_type, name, customer_id)
        VALUES (:id, :account_type, :name, :customer_id)
        ON CONFLICT DO NOTHING
        """,
        inst_rows,
    )

    # Generate transactions over 60 days. Keep total around ~20k (plus salsa seed).
    tx_rows: list[dict[str, Any]] = []
    tx_count = 0
    payment_weights = [
        (PaymentType.loyalty.value, 0.50),
        (PaymentType.credit_with_email.value, 0.25),
        (PaymentType.cash.value, 0.20),
        (PaymentType.third_party.value, 0.05),
    ]

    def pick_payment() -> str:
        r = rng.random()
        cum = 0.0
        for pt, w in payment_weights:
            cum += w
            if r <= cum:
                return pt
        return PaymentType.cash.value

    for i, cid in enumerate(customer_ids):
        preferred_store = uuid.UUID(customer_rows[i]["profile"]["preferred_store_id"])
        frequent_upcs = customer_rows[i]["profile"]["frequent_upcs"]
        # 6-14 purchases across 60 days
        for j in range(rng.randint(6, 14)):
            day = rng.randrange(0, 60)
            store_id = preferred_store if rng.random() < 0.9 else rng.choice(store_ids)
            tm = _dt(day) + timedelta(hours=rng.choice([10, 12, 16, 18]))
            upc = rng.choice(frequent_upcs)
            lot_capture = rng.random() < 0.2
            li: dict[str, Any] = {
                "finished_product_id": str(ids.finished_products[upc]),
                "quantity_units": 1,
            }
            if lot_capture:
                # pick a deterministic lot id "as if" captured; not guaranteed to exist
                li["finished_product_lot_id"] = str(det_uuid("fpl", f"CAP-{upc}-{day}"))
            tx_rows.append(
                {
                    "id": det_uuid("tx", str(i), str(j)),
                    "store_id": store_id,
                    "customer_id": cid,
                    "timestamp": tm,
                    "payment_type": pick_payment(),
                    "line_items": [li],
                }
            )
            tx_count += 1

    # Salsa seed: ~1,800 transactions of Salsa Verde UPC across affected stores in the window.
    if scenario in {"salsa_verde", "both"}:
        affected_store_ids = [ids.stores[name] for name in salsa_verde_seed.ACME_AFFECTED_STORE_NAMES]
        start = salsa_verde_seed.SHIP_WINDOW_START_UTC
        end = salsa_verde_seed.SHIP_WINDOW_END_UTC
        window_days = (end - start).days + 1
        for i in range(1800):
            store_id = affected_store_ids[i % len(affected_store_ids)]
            tm = start + timedelta(days=i % window_days, hours=12 + (i % 6))
            tx_rows.append(
                {
                    "id": det_uuid("tx_salsa", str(i)),
                    "store_id": store_id,
                    "customer_id": None,
                    "timestamp": tm,
                    "payment_type": PaymentType.cash.value,
                    "line_items": [
                        {
                            "finished_product_id": str(ids.finished_products[salsa_verde_seed.FINISHED_PRODUCT_UPC]),
                            "quantity_units": 1,
                        }
                    ],
                }
            )
        tx_count += 1800

    # Store-4-Fridge seed: ~75 transactions for refrigerated products in the failure window (Store 4 only).
    if scenario in {"store4_fridge", "both"}:
        store4_id = ids.stores[store4_fridge_seed.STORE_NAME]
        # Pick 12 "refrigerated" products deterministically (excluding the salsa UPC if present)
        refrigerated_upcs = [u for u in upcs if u != salsa_verde_seed.FINISHED_PRODUCT_UPC][:12]
        start = store4_fridge_seed.FAILURE_AT_UTC
        end = store4_fridge_seed.DISCOVERED_AT_UTC
        window_seconds = int((end - start).total_seconds())
        for i in range(75):
            tm = start + timedelta(seconds=(i * 60) % max(window_seconds, 1))
            upc = refrigerated_upcs[i % len(refrigerated_upcs)]
            tx_rows.append(
                {
                    "id": det_uuid("tx_store4_fridge", str(i)),
                    "store_id": store4_id,
                    "customer_id": None,
                    "timestamp": tm,
                    "payment_type": PaymentType.cash.value,
                    "line_items": [
                        {"finished_product_id": str(ids.finished_products[upc]), "quantity_units": 1}
                    ],
                }
            )
        tx_count += 75

    insert_many(
        engine,
        """
        INSERT INTO pos_transactions (id, store_id, customer_id, timestamp, payment_type, line_items)
        VALUES (:id, :store_id, :customer_id, :timestamp, :payment_type, CAST(:line_items AS jsonb))
        ON CONFLICT DO NOTHING
        """,
        tx_rows,
    )

    return {"customers": len(customer_rows), "transactions": tx_count, "institutional_accounts": len(inst_rows)}


def generate_refrigeration(engine: Engine, ids: StaticIds, seed: int, scenario: str) -> dict[str, int]:
    rng = random.Random(seed + 3)
    zone_rows: list[dict[str, Any]] = []
    for store_name, store_id in ids.stores.items():
        # 2 zones per store
        for z in ["Deli_Fridge", "Freezer"]:
            name = f"{store_name}_{z}"
            zone_rows.append({"id": det_uuid("zone", name), "store_id": store_id, "name": name})
    # Ensure Store4_Deli_Fridge exact zone name exists
    zone_rows.append(
        {
            "id": det_uuid("zone", store4_fridge_seed.ZONE_NAME),
            "store_id": ids.stores[store4_fridge_seed.STORE_NAME],
            "name": store4_fridge_seed.ZONE_NAME,
        }
    )

    insert_many(
        engine,
        """
        INSERT INTO refrigeration_zones (id, store_id, name)
        VALUES (:id, :store_id, :name)
        ON CONFLICT DO NOTHING
        """,
        zone_rows,
    )

    # Sparse events: mostly inspections.
    event_rows: list[dict[str, Any]] = []
    for i in range(50):
        zone = rng.choice(zone_rows)
        event_rows.append(
            {
                "id": det_uuid("refrig_evt", str(i)),
                "zone_id": zone["id"],
                "event_type": "inspection",
                "timestamp": _dt(rng.randrange(0, 60)),
                "details": {"ok": True},
            }
        )

    if scenario in {"store4_fridge", "both"}:
        zone_id = det_uuid("zone", store4_fridge_seed.ZONE_NAME)
        event_rows.append(
            {
                "id": det_uuid("refrig_evt", "failure"),
                "zone_id": zone_id,
                "event_type": "failure",
                "timestamp": store4_fridge_seed.FAILURE_AT_UTC,
                "details": {"discovered_at_utc": store4_fridge_seed.DISCOVERED_AT_UTC.isoformat()},
            }
        )
        event_rows.append(
            {
                "id": det_uuid("refrig_evt", "restored"),
                "zone_id": zone_id,
                "event_type": "restored",
                "timestamp": store4_fridge_seed.RESTORED_AT_UTC,
                "details": {},
            }
        )

    insert_many(
        engine,
        """
        INSERT INTO refrigeration_events (id, zone_id, event_type, timestamp, details)
        VALUES (:id, :zone_id, :event_type, :timestamp, CAST(:details AS jsonb))
        ON CONFLICT DO NOTHING
        """,
        event_rows,
    )

    return {"refrigeration_zones": len(zone_rows), "refrigeration_events": len(event_rows)}


def print_summary(engine: Engine, scenario: str) -> None:
    tables = [
        "suppliers",
        "ingredients",
        "ingredient_lots",
        "manufacturers",
        "facilities",
        "production_runs",
        "finished_products",
        "finished_product_lots",
        "pallets",
        "shipments",
        "distributors",
        "distributor_warehouses",
        "stores",
        "store_shipments",
        "stocking_events",
        "pos_transactions",
        "customers",
        "institutional_accounts",
        "refrigeration_zones",
        "refrigeration_events",
    ]
    with engine.begin() as conn:
        counts = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in tables}

    print("=== Pheromone synthetic data summary ===")
    for t in tables:
        print(f"{t}: {counts[t]}")
    print(f"scenario: {scenario}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic Pheromone supply-chain data.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="both")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL") or os.environ.get("PHEROMONE_DATABASE_URL"))
    args = parser.parse_args()

    if not args.db_url:
        raise SystemExit("DATABASE_URL (or --db-url) is required.")

    engine = connect(args.db_url)
    if args.reset:
        reset_all_tables(engine)

    ids = generate_static_seeds(engine, args.seed)
    generate_time_series(engine, ids, args.seed, args.scenario)
    generate_customers_and_transactions(engine, ids, args.seed, args.scenario)
    generate_refrigeration(engine, ids, args.seed, args.scenario)
    print_summary(engine, args.scenario)


if __name__ == "__main__":
    main()
