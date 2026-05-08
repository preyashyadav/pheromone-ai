from __future__ import annotations

import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.agents.intake_agent import ExtractedString, RecallSpec as IntakeRecallSpec
from backend.agents.trace_agent import TraceAgent
from backend.engine.composition_engine import (
    InventoryCompositionEngine,
    _SaleEvent,
    _StockEvent,
    compute_composition_from_events,
)
from backend.engine.recall_graph import BlastRadius


def test_phase5_composition_engine_math_correct_proportional_sales() -> None:
    t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    pallet_a = uuid.uuid4()
    pallet_b = uuid.uuid4()

    stock = [
        _StockEvent(timestamp=t0, pallet_id=pallet_a, units_added=60),
        _StockEvent(timestamp=t0, pallet_id=pallet_b, units_added=40),
    ]
    sales = [_SaleEvent(timestamp=t0 + timedelta(hours=1), units_sold=10)]
    got = compute_composition_from_events(stock_events=stock, sale_events=sales)
    assert abs(got[pallet_a] - 0.6) < 1e-6
    assert abs(got[pallet_b] - 0.4) < 1e-6


def test_phase5_composition_engine_sales_when_empty_returns_empty() -> None:
    t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    got = compute_composition_from_events(stock_events=[], sale_events=[_SaleEvent(timestamp=t0, units_sold=3)])
    assert got == {}


def test_phase5_composition_engine_snapshot_cache_hit_is_fast(engine) -> None:
    # Build a tiny fixture in Postgres and ensure second query uses hot cache path.
    t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    with Session(engine) as s:
        s.execute(text("INSERT INTO suppliers (id, name) VALUES (:id, :n)"), {"id": uuid.uuid4(), "n": "S"})
        man = uuid.uuid4()
        s.execute(text("INSERT INTO manufacturers (id, name) VALUES (:id, :n)"), {"id": man, "n": "M"})
        facility = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO facilities (id, manufacturer_id, name, plant_code, timezone) VALUES (:id, :mid, :n, :pc, 'UTC')"
            ),
            {"id": facility, "mid": man, "n": "Plant", "pc": "PZ"},
        )
        store = uuid.uuid4()
        s.execute(text("INSERT INTO stores (id, name, timezone) VALUES (:id, :n, 'UTC')"), {"id": store, "n": "Store"})
        wh = uuid.uuid4()
        dist = uuid.uuid4()
        s.execute(text("INSERT INTO distributors (id, name) VALUES (:id, :n)"), {"id": dist, "n": "D"})
        s.execute(
            text(
                "INSERT INTO distributor_warehouses (id, distributor_id, name, timezone) VALUES (:id, :did, :n, 'UTC')"
            ),
            {"id": wh, "did": dist, "n": "WH"},
        )
        product = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO finished_products (id, manufacturer_id, name, upc, ingredient_recipe) VALUES (:id, :mid, :n, :upc, '[]'::jsonb)"
            ),
            {"id": product, "mid": man, "n": "P", "upc": "000000000000"},
        )
        pr = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO production_runs (id, facility_id, started_at, ended_at, ingredient_lots_used) VALUES (:id, :fid, :st, :en, '[]'::jsonb)"
            ),
            {"id": pr, "fid": facility, "st": t0, "en": t0},
        )
        fpl = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO finished_product_lots (id, finished_product_id, production_run_id, lot_code, produced_at, best_by_date) VALUES (:id, :pid, :pr, :lc, :pa, :bb)"
            ),
            {"id": fpl, "pid": product, "pr": pr, "lc": "PZ-040126-A", "pa": t0, "bb": t0 + timedelta(days=100)},
        )
        ss = uuid.uuid4()
        s.execute(
            text("INSERT INTO store_shipments (id, warehouse_id, store_id, shipped_at, arrived_at) VALUES (:id, :wh, :sid, :st, :ar)"),
            {"id": ss, "wh": wh, "sid": store, "st": t0, "ar": t0 + timedelta(hours=6)},
        )
        pallet_a = uuid.uuid4()
        pallet_b = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO pallets (id, finished_product_lot_id, shipment_id, store_shipment_id, units_total) VALUES (:id, :fpl, NULL, :ss, 100)"
            ),
            {"id": pallet_a, "fpl": fpl, "ss": ss},
        )
        s.execute(
            text(
                "INSERT INTO pallets (id, finished_product_lot_id, shipment_id, store_shipment_id, units_total) VALUES (:id, :fpl, NULL, :ss, 100)"
            ),
            {"id": pallet_b, "fpl": fpl, "ss": ss},
        )
        s.execute(
            text(
                "INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added) VALUES (gen_random_uuid(), :sid, :pid, :fp, :ts, :u)"
            ),
            {"sid": store, "pid": pallet_a, "fp": product, "ts": t0 + timedelta(hours=1), "u": 60},
        )
        s.execute(
            text(
                "INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added) VALUES (gen_random_uuid(), :sid, :pid, :fp, :ts, :u)"
            ),
            {"sid": store, "pid": pallet_b, "fp": product, "ts": t0 + timedelta(hours=1, minutes=5), "u": 40},
        )
        s.commit()

    from backend.db.repositories import make_session_factory

    session_factory = make_session_factory(engine)
    comp = InventoryCompositionEngine(session_factory)
    at = t0 + timedelta(hours=2)

    t1 = time.perf_counter()
    a = comp.compute_composition(store, product, at)
    d1 = time.perf_counter() - t1

    t2 = time.perf_counter()
    b = comp.compute_composition(store, product, at)
    d2 = time.perf_counter() - t2

    assert a == b
    # Heuristic: second call should be substantially faster (in-proc cache + snapshot table).
    assert d2 < (d1 / 3.0)


def test_phase5_composition_engine_probabilistic_correctness_60_40(engine) -> None:
    """
    Phase 5 test case #8:
      Store has 60% clean Pallet A + 40% affected Pallet C at time T.
      Query at T+epsilon returns affected probability ~= 0.40 ± 0.02.
    """
    t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    with Session(engine) as s:
        s.execute(text("INSERT INTO suppliers (id, name) VALUES (:id, :n)"), {"id": uuid.uuid4(), "n": "S2"})
        man = uuid.uuid4()
        s.execute(text("INSERT INTO manufacturers (id, name) VALUES (:id, :n)"), {"id": man, "n": "M2"})
        facility = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO facilities (id, manufacturer_id, name, plant_code, timezone) VALUES (:id, :mid, :n, :pc, 'UTC')"
            ),
            {"id": facility, "mid": man, "n": "Plant2", "pc": "PX"},
        )
        store = uuid.uuid4()
        s.execute(text("INSERT INTO stores (id, name, timezone) VALUES (:id, :n, 'UTC')"), {"id": store, "n": "Store2"})
        wh = uuid.uuid4()
        dist = uuid.uuid4()
        s.execute(text("INSERT INTO distributors (id, name) VALUES (:id, :n)"), {"id": dist, "n": "D2"})
        s.execute(
            text(
                "INSERT INTO distributor_warehouses (id, distributor_id, name, timezone) VALUES (:id, :did, :n, 'UTC')"
            ),
            {"id": wh, "did": dist, "n": "WH2"},
        )
        product = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO finished_products (id, manufacturer_id, name, upc, ingredient_recipe) VALUES (:id, :mid, :n, :upc, '[]'::jsonb)"
            ),
            {"id": product, "mid": man, "n": "P2", "upc": "000000000999"},
        )
        pr = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO production_runs (id, facility_id, started_at, ended_at, ingredient_lots_used) VALUES (:id, :fid, :st, :en, '[]'::jsonb)"
            ),
            {"id": pr, "fid": facility, "st": t0, "en": t0},
        )
        fpl = uuid.uuid4()
        s.execute(
            text(
                "INSERT INTO finished_product_lots (id, finished_product_id, production_run_id, lot_code, produced_at, best_by_date) VALUES (:id, :pid, :pr, :lc, :pa, :bb)"
            ),
            {"id": fpl, "pid": product, "pr": pr, "lc": "PX-040126-A", "pa": t0, "bb": t0 + timedelta(days=100)},
        )
        ss = uuid.uuid4()
        s.execute(
            text("INSERT INTO store_shipments (id, warehouse_id, store_id, shipped_at, arrived_at) VALUES (:id, :wh, :sid, :st, :ar)"),
            {"id": ss, "wh": wh, "sid": store, "st": t0, "ar": t0 + timedelta(hours=6)},
        )
        pallet_a = uuid.uuid4()  # clean
        pallet_c = uuid.uuid4()  # affected
        s.execute(
            text(
                "INSERT INTO pallets (id, finished_product_lot_id, shipment_id, store_shipment_id, units_total) VALUES (:id, :fpl, NULL, :ss, 100)"
            ),
            {"id": pallet_a, "fpl": fpl, "ss": ss},
        )
        s.execute(
            text(
                "INSERT INTO pallets (id, finished_product_lot_id, shipment_id, store_shipment_id, units_total) VALUES (:id, :fpl, NULL, :ss, 100)"
            ),
            {"id": pallet_c, "fpl": fpl, "ss": ss},
        )
        # Stock at the same moment (T): 60 vs 40.
        t_stock = t0 + timedelta(hours=1)
        s.execute(
            text(
                "INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added) VALUES (gen_random_uuid(), :sid, :pid, :fp, :ts, :u)"
            ),
            {"sid": store, "pid": pallet_a, "fp": product, "ts": t_stock, "u": 60},
        )
        s.execute(
            text(
                "INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added) VALUES (gen_random_uuid(), :sid, :pid, :fp, :ts, :u)"
            ),
            {"sid": store, "pid": pallet_c, "fp": product, "ts": t_stock, "u": 40},
        )
        s.commit()

    from backend.db.repositories import make_session_factory

    comp = InventoryCompositionEngine(make_session_factory(engine))
    got = comp.compute_composition(store, product, t_stock + timedelta(seconds=1))
    affected_prob = got.get(pallet_c, 0.0)
    assert abs(affected_prob - 0.40) <= 0.02


def _run_generator(db_url: str, scenario: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    p = subprocess.run(
        [
            str(repo_root / ".venv" / "bin" / "python"),
            str(repo_root / "data_generator" / "generate.py"),
            "--db-url",
            db_url,
            "--seed",
            "42",
            "--scenario",
            scenario,
            "--reset",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr


def test_phase5_trace_agent_salsa_verde_returns_exact_6_affected_stores(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed

    _run_generator(db_url, "salsa_verde")

    # Minimal RecallSpec: just the ingredient lot code is enough for deterministic trace.
    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity="high",
        hazard_type="other",
        hazard_details="",
        symptom_timeline_days=(None, None),
        remedy_instructions="",
        extraction_confidence={"product_identifiers": 0.4, "hazard_type": 0.6, "severity": 0.6},
        raw_notice_text="",
    )

    from backend.db.repositories import make_session_factory

    agent = TraceAgent(make_session_factory(engine))
    blast = agent.build(recall_spec)
    assert isinstance(blast, BlastRadius)

    with engine.begin() as conn:
        expected_store_ids = set(
            conn.execute(
                text("SELECT id FROM stores WHERE name = ANY(CAST(:names AS text[]))"),
                {"names": salsa_verde_seed.ACME_AFFECTED_STORE_NAMES},
            ).scalars().all()
        )

    got_store_ids = {s.store_id for s in blast.affected_stores}
    assert got_store_ids == expected_store_ids
    assert all(abs(s.affected_stock_fraction_peak - 1.0) < 1e-9 for s in blast.affected_stores)


def test_phase5_trace_agent_store4_fridge_returns_only_store4(db_url, engine) -> None:
    from data_generator.seeds import store4_fridge_seed

    _run_generator(db_url, "store4_fridge")

    with engine.begin() as conn:
        store4_id = conn.execute(
            text("SELECT id FROM stores WHERE name = :n"), {"n": store4_fridge_seed.STORE_NAME}
        ).scalar_one()

    recall_spec = IntakeRecallSpec(
        recall_id="store-4-fridge",
        source_type="retailer_internal",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[{"product_name": "refrigeration zone temp excursion"}],
        lot_codes=[],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity="high",
        hazard_type="other",
        hazard_details="",
        symptom_timeline_days=(None, None),
        remedy_instructions="",
        extraction_confidence={"product_identifiers": 0.7, "hazard_type": 0.6, "severity": 0.7},
        raw_notice_text="",
    )

    from backend.db.repositories import make_session_factory

    agent = TraceAgent(make_session_factory(engine))
    blast = agent.build(
        recall_spec,
        store_id=uuid.UUID(str(store4_id)),
        time_window={"start": store4_fridge_seed.FAILURE_AT_UTC.isoformat().replace("+00:00", "Z"), "end": store4_fridge_seed.DISCOVERED_AT_UTC.isoformat().replace("+00:00", "Z")},
    )
    assert {s.store_id for s in blast.affected_stores} == {uuid.UUID(str(store4_id))}


def test_phase5_trace_agent_infers_facility_from_lot_code_pattern(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed

    _run_generator(db_url, "salsa_verde")

    recall_spec = IntakeRecallSpec(
        recall_id="P2-052126-A",
        source_type="openfda",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value="P2-052126-A", confidence=0.9)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=["Texas"],
        severity="critical",
        hazard_type="salmonella",
        hazard_details="",
        symptom_timeline_days=(None, None),
        remedy_instructions="",
        extraction_confidence={"product_identifiers": 0.7, "hazard_type": 0.9, "severity": 0.9},
        raw_notice_text="",
    )

    from backend.db.repositories import make_session_factory

    agent = TraceAgent(make_session_factory(engine))
    blast = agent.build(
        recall_spec,
        time_window={"start": salsa_verde_seed.RG4429_WINDOW_START_UTC.isoformat().replace("+00:00", "Z"), "end": salsa_verde_seed.RG4429_WINDOW_END_UTC.isoformat().replace("+00:00", "Z")},
    )
    assert len(blast.inferred_facility_ids) == 1
    ((fid, conf),) = list(blast.inferred_facility_ids.items())
    assert conf >= 0.7


def test_phase5_trace_agent_hierarchical_propagation_mentions_blend_products(db_url, engine) -> None:
    _run_generator(db_url, "salsa_verde")

    # Identify an actual ingredient lot for roasted_garlic_paste from the seeded dataset.
    with engine.begin() as conn:
        lot_id = conn.execute(
            text(
                """
                SELECT il.lot_code
                FROM ingredient_lots il
                JOIN ingredients i ON i.id = il.ingredient_id
                WHERE i.name = 'roasted_garlic_paste'
                ORDER BY il.received_at
                LIMIT 1
                """
            )
        ).scalar_one()

    recall_spec = IntakeRecallSpec(
        recall_id=str(lot_id),
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=str(lot_id), confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity="high",
        hazard_type="other",
        hazard_details="",
        symptom_timeline_days=(None, None),
        remedy_instructions="",
        extraction_confidence={"product_identifiers": 0.4, "hazard_type": 0.6, "severity": 0.6},
        raw_notice_text="",
    )

    from backend.db.repositories import make_session_factory

    agent = TraceAgent(make_session_factory(engine))
    blast = agent.build(recall_spec)

    # At least 5 finished products should reference seasoning_blend_X in the generator.
    assert len(blast.affected_finished_product_ids) >= 5
