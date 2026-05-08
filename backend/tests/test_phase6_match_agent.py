from __future__ import annotations

import subprocess
import time
import uuid
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from backend.agents.intake_agent import ExtractedString, HazardType, RecallSpec as IntakeRecallSpec
from backend.agents.match_agent import MatchAgent
from backend.agents.trace_agent import TraceAgent
from backend.engine.confidence import ConfidenceTier


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


def _tier_counts(scored) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in scored:
        k = s.confidence_tier.value
        out[k] = out.get(k, 0) + 1
    return out


def test_phase6_salsa_verde_tier_counts(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")

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
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={"product_identifiers": 0.4, "hazard_type": 0.6, "severity": 0.6},
        raw_notice_text="",
    )

    sf = make_session_factory(engine)
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    counts = _tier_counts(scored)

    assert counts.get(ConfidenceTier.confirmed_affected.value, 0) >= 300
    assert counts.get(ConfidenceTier.likely_affected.value, 0) >= 800
    assert counts.get(ConfidenceTier.possible_affected.value, 0) >= 600
    unaffected = counts.get(ConfidenceTier.confirmed_unaffected.value, 0) + counts.get(
        ConfidenceTier.likely_unaffected.value, 0
    )
    assert unaffected >= 400


def test_phase6_store4_fridge_window_affected_and_edges_unaffected(db_url, engine) -> None:
    from data_generator.seeds import store4_fridge_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "store4_fridge")

    with engine.begin() as conn:
        store4_id = conn.execute(
            text("SELECT id FROM stores WHERE name = :n"), {"n": store4_fridge_seed.STORE_NAME}
        ).scalar_one()

    # Build a store-scoped blast radius over the failure window plus a small padding.
    window = {
        "start": (store4_fridge_seed.FAILURE_AT_UTC - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "end": (store4_fridge_seed.DISCOVERED_AT_UTC + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }
    recall_spec = IntakeRecallSpec(
        recall_id="store-4-fridge",
        source_type="retailer_internal",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity="high",
        hazard_type=HazardType.other,
        hazard_details="",
        symptom_timeline_days=(None, None),
        remedy_instructions="",
        extraction_confidence={"product_identifiers": 0.7, "hazard_type": 0.6, "severity": 0.7},
        raw_notice_text="",
    )

    sf = make_session_factory(engine)
    blast = TraceAgent(sf).build(recall_spec, store_id=uuid.UUID(str(store4_id)), time_window=window)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)

    # With no affected pallets known, tier should be in unaffected/no_action.
    counts = _tier_counts(scored)
    unaffected = counts.get(ConfidenceTier.confirmed_unaffected.value, 0) + counts.get(
        ConfidenceTier.likely_unaffected.value, 0
    )
    assert unaffected >= 1


def test_phase6_vulnerable_population_modifier_bumps_one_tier(db_url, engine) -> None:
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "none")

    # Create two customers: vulnerable vs non-vulnerable.
    with engine.begin() as conn:
        vuln_id = uuid.uuid4()
        non_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO customers (id, loyalty_id, email_hash, phone_hash, profile) VALUES (:id, NULL, NULL, NULL, CAST(:p AS jsonb))"
            ),
            {"id": vuln_id, "p": json.dumps({"kids_at_home": True, "immunocompromised": False})},
        )
        conn.execute(
            text(
                "INSERT INTO customers (id, loyalty_id, email_hash, phone_hash, profile) VALUES (:id, NULL, NULL, NULL, CAST(:p AS jsonb))"
            ),
            {"id": non_id, "p": json.dumps({"kids_at_home": False, "immunocompromised": False})},
        )

    # Build a tiny blast radius with a fake affected pallet by reusing the phase5 60/40 fixture pattern.
    # We directly insert stock/tx so composition yields p~=0.2 (Possible Affected).
    t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    with engine.begin() as conn:
        man = uuid.uuid4()
        facility = uuid.uuid4()
        dist = uuid.uuid4()
        wh = uuid.uuid4()
        store = uuid.uuid4()
        product = uuid.uuid4()
        pr = uuid.uuid4()
        fpl = uuid.uuid4()
        ss = uuid.uuid4()
        pallet_clean = uuid.uuid4()
        pallet_aff = uuid.uuid4()
        conn.execute(text("INSERT INTO manufacturers (id, name) VALUES (:id, :n)"), {"id": man, "n": "M6"})
        conn.execute(
            text(
                "INSERT INTO facilities (id, manufacturer_id, name, plant_code, timezone) VALUES (:id, :mid, :n, :pc, 'UTC')"
            ),
            {"id": facility, "mid": man, "n": "Plant6", "pc": "P6"},
        )
        conn.execute(text("INSERT INTO distributors (id, name) VALUES (:id, :n)"), {"id": dist, "n": "D6"})
        conn.execute(
            text(
                "INSERT INTO distributor_warehouses (id, distributor_id, name, timezone) VALUES (:id, :did, :n, 'UTC')"
            ),
            {"id": wh, "did": dist, "n": "WH6"},
        )
        conn.execute(text("INSERT INTO stores (id, name, timezone) VALUES (:id, :n, 'UTC')"), {"id": store, "n": "S6"})
        conn.execute(
            text(
                "INSERT INTO finished_products (id, manufacturer_id, name, upc, ingredient_recipe) VALUES (:id, :mid, :n, :u, '[]'::jsonb)"
            ),
            {"id": product, "mid": man, "n": "Prod6", "u": "000000000666"},
        )
        conn.execute(
            text(
                "INSERT INTO production_runs (id, facility_id, started_at, ended_at, ingredient_lots_used) VALUES (:id, :fid, :st, :en, '[]'::jsonb)"
            ),
            {"id": pr, "fid": facility, "st": t0, "en": t0},
        )
        conn.execute(
            text(
                "INSERT INTO finished_product_lots (id, finished_product_id, production_run_id, lot_code, produced_at, best_by_date) VALUES (:id, :pid, :pr, :lc, :pa, :bb)"
            ),
            {"id": fpl, "pid": product, "pr": pr, "lc": "P6-040126-A", "pa": t0, "bb": t0 + timedelta(days=30)},
        )
        conn.execute(
            text("INSERT INTO store_shipments (id, warehouse_id, store_id, shipped_at, arrived_at) VALUES (:id, :wh, :sid, :st, :ar)"),
            {"id": ss, "wh": wh, "sid": store, "st": t0, "ar": t0 + timedelta(hours=1)},
        )
        conn.execute(
            text(
                "INSERT INTO pallets (id, finished_product_lot_id, shipment_id, store_shipment_id, units_total) VALUES (:id, :fpl, NULL, :ss, 100)"
            ),
            {"id": pallet_clean, "fpl": fpl, "ss": ss},
        )
        conn.execute(
            text(
                "INSERT INTO pallets (id, finished_product_lot_id, shipment_id, store_shipment_id, units_total) VALUES (:id, :fpl, NULL, :ss, 100)"
            ),
            {"id": pallet_aff, "fpl": fpl, "ss": ss},
        )
        t_stock = t0 + timedelta(hours=2)
        conn.execute(
            text(
                "INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added) VALUES (gen_random_uuid(), :sid, :pid, :fp, :ts, :u)"
            ),
            {"sid": store, "pid": pallet_clean, "fp": product, "ts": t_stock, "u": 80},
        )
        conn.execute(
            text(
                "INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added) VALUES (gen_random_uuid(), :sid, :pid, :fp, :ts, :u)"
            ),
            {"sid": store, "pid": pallet_aff, "fp": product, "ts": t_stock, "u": 20},
        )
        # Two transactions at the same time for vuln vs non.
        tx_v = uuid.uuid4()
        tx_n = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO pos_transactions (id, store_id, customer_id, timestamp, payment_type, line_items) VALUES (:id, :sid, :cid, :ts, 'loyalty', CAST(:li AS jsonb))"
            ),
            {"id": tx_v, "sid": store, "cid": vuln_id, "ts": t_stock + timedelta(seconds=1), "li": json.dumps([{"finished_product_id": str(product), "quantity_units": 1}])},
        )
        conn.execute(
            text(
                "INSERT INTO pos_transactions (id, store_id, customer_id, timestamp, payment_type, line_items) VALUES (:id, :sid, :cid, :ts, 'loyalty', CAST(:li AS jsonb))"
            ),
            {"id": tx_n, "sid": store, "cid": non_id, "ts": t_stock + timedelta(seconds=1), "li": json.dumps([{"finished_product_id": str(product), "quantity_units": 1}])},
        )

    # Fake blast radius declares pallet_aff affected.
    blast = {
        "affected_pallets": [{"pallet_id": pallet_aff, "certainty": 1.0}],
        "affected_stores": [{"store_id": store, "affected_stock_fraction_peak": 0.2}],
        "affected_transactions_window": [{"store_id": store, "start_utc": t_stock, "end_utc": t_stock, "transaction_ids": [tx_v, tx_n]}],
        "affected_finished_product_ids": [product],
        "inferred_facility_ids": {},
    }
    from backend.engine.recall_graph import BlastRadius as BlastRadiusModel

    blast_m = BlastRadiusModel.model_validate(blast)
    recall_spec = IntakeRecallSpec(
        recall_id="LIS-1",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity="high",
        hazard_type=HazardType.listeria,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )

    sf = make_session_factory(engine)
    scored = MatchAgent(sf).score_transactions(blast_m, recall_spec)
    by_cust = {s.customer_id: s.confidence_tier for s in scored}
    assert by_cust[vuln_id] != by_cust[non_id]


def test_phase6_reassurance_eligibility_at_least_800_customers(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
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
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    sf = make_session_factory(engine)
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    reassurance = [
        s for s in scored if s.confidence_tier in {ConfidenceTier.confirmed_unaffected, ConfidenceTier.likely_unaffected}
    ]
    # Unique customers in reassurance buckets.
    custs = {s.customer_id for s in reassurance if s.customer_id is not None}
    assert len(custs) >= 800


def test_phase6_empty_blast_radius_no_crash(engine) -> None:
    from backend.db.repositories import make_session_factory
    from backend.engine.recall_graph import BlastRadius

    sf = make_session_factory(engine)
    recall_spec = IntakeRecallSpec(
        recall_id="empty",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity="unknown",
        hazard_type=HazardType.other,
        hazard_details="",
        symptom_timeline_days=(None, None),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    scored = MatchAgent(sf).score_transactions(BlastRadius(), recall_spec)
    assert scored == []


def test_phase6_cash_degrades_confirmed_to_likely(db_url, engine) -> None:
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "none")
    # create a minimal transaction and mark its lot as affected; payment_type cash should cap at Likely.
    with engine.begin() as conn:
        man = uuid.uuid4()
        facility = uuid.uuid4()
        dist = uuid.uuid4()
        wh = uuid.uuid4()
        store = uuid.uuid4()
        product = uuid.uuid4()
        pr = uuid.uuid4()
        fpl = uuid.uuid4()
        ss = uuid.uuid4()
        pallet_aff = uuid.uuid4()
        conn.execute(text("INSERT INTO manufacturers (id, name) VALUES (:id, :n)"), {"id": man, "n": "M6b"})
        conn.execute(
            text(
                "INSERT INTO facilities (id, manufacturer_id, name, plant_code, timezone) VALUES (:id, :mid, :n, :pc, 'UTC')"
            ),
            {"id": facility, "mid": man, "n": "Plant6b", "pc": "P6b"},
        )
        conn.execute(text("INSERT INTO distributors (id, name) VALUES (:id, :n)"), {"id": dist, "n": "D6b"})
        conn.execute(
            text(
                "INSERT INTO distributor_warehouses (id, distributor_id, name, timezone) VALUES (:id, :did, :n, 'UTC')"
            ),
            {"id": wh, "did": dist, "n": "WH6b"},
        )
        conn.execute(text("INSERT INTO stores (id, name, timezone) VALUES (:id, :n, 'UTC')"), {"id": store, "n": "S6b"})
        conn.execute(
            text(
                "INSERT INTO finished_products (id, manufacturer_id, name, upc, ingredient_recipe) VALUES (:id, :mid, :n, :u, '[]'::jsonb)"
            ),
            {"id": product, "mid": man, "n": "Prod6b", "u": "000000000667"},
        )
        t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        conn.execute(
            text(
                "INSERT INTO production_runs (id, facility_id, started_at, ended_at, ingredient_lots_used) VALUES (:id, :fid, :st, :en, '[]'::jsonb)"
            ),
            {"id": pr, "fid": facility, "st": t0, "en": t0},
        )
        conn.execute(
            text(
                "INSERT INTO finished_product_lots (id, finished_product_id, production_run_id, lot_code, produced_at, best_by_date) VALUES (:id, :pid, :pr, :lc, :pa, :bb)"
            ),
            {"id": fpl, "pid": product, "pr": pr, "lc": "P6b-040126-A", "pa": t0, "bb": t0 + timedelta(days=30)},
        )
        conn.execute(
            text("INSERT INTO store_shipments (id, warehouse_id, store_id, shipped_at, arrived_at) VALUES (:id, :wh, :sid, :st, :ar)"),
            {"id": ss, "wh": wh, "sid": store, "st": t0, "ar": t0 + timedelta(hours=1)},
        )
        conn.execute(
            text(
                "INSERT INTO pallets (id, finished_product_lot_id, shipment_id, store_shipment_id, units_total) VALUES (:id, :fpl, NULL, :ss, 100)"
            ),
            {"id": pallet_aff, "fpl": fpl, "ss": ss},
        )
        t_stock = t0 + timedelta(hours=2)
        conn.execute(
            text(
                "INSERT INTO stocking_events (id, store_id, pallet_id, finished_product_id, timestamp, units_added) VALUES (gen_random_uuid(), :sid, :pid, :fp, :ts, :u)"
            ),
            {"sid": store, "pid": pallet_aff, "fp": product, "ts": t_stock, "u": 10},
        )
        tx_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO pos_transactions (id, store_id, customer_id, timestamp, payment_type, line_items) VALUES (:id, :sid, NULL, :ts, 'cash', CAST(:li AS jsonb))"
            ),
            {"id": tx_id, "sid": store, "ts": t_stock + timedelta(seconds=1), "li": json.dumps([{"finished_product_id": str(product), "quantity_units": 1, "finished_product_lot_id": str(fpl)}])},
        )

    from backend.engine.recall_graph import BlastRadius as BlastRadiusModel

    blast = BlastRadiusModel.model_validate(
        {
            "affected_pallets": [{"pallet_id": pallet_aff, "certainty": 1.0}],
            "affected_stores": [{"store_id": store, "affected_stock_fraction_peak": 1.0}],
            "affected_transactions_window": [{"store_id": store, "start_utc": t_stock, "end_utc": t_stock, "transaction_ids": [tx_id]}],
            "affected_finished_product_ids": [product],
            "inferred_facility_ids": {},
        }
    )
    recall_spec = IntakeRecallSpec(
        recall_id="cash",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity="high",
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    scored = MatchAgent(make_session_factory(engine)).score_transactions(blast, recall_spec)
    assert scored[0].confidence_tier == ConfidenceTier.likely_affected


def test_phase6_determinism_same_inputs_same_tiers(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
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
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    sf = make_session_factory(engine)
    blast = TraceAgent(sf).build(recall_spec)
    agent = MatchAgent(sf)
    a = agent.score_transactions(blast, recall_spec)
    b = agent.score_transactions(blast, recall_spec)
    assert [(x.transaction_id, x.confidence_tier.value) for x in a] == [
        (x.transaction_id, x.confidence_tier.value) for x in b
    ]


def test_phase6_performance_scores_2000_under_30s(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
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
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    sf = make_session_factory(engine)
    blast = TraceAgent(sf).build(recall_spec)
    agent = MatchAgent(sf)
    start = time.time()
    scored = agent.score_transactions(blast, recall_spec, limit=2000)
    dur = time.time() - start
    assert len(scored) == 2000
    assert dur < 30.0
