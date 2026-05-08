from __future__ import annotations

import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json

from sqlalchemy import text

from backend.agents.intake_agent import ExtractedString, HazardType, RecallSpec as IntakeRecallSpec, Severity
from backend.agents.match_agent import MatchAgent
from backend.agents.ops_agent import OpsAgent, TaskType
from backend.agents.trace_agent import TraceAgent


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


def test_phase7_ops_agent_salsa_verde_generates_task_lists_per_store(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory, RecallRepository

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)
    recall_case_id = RecallRepository(sf).create_recall_case()

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
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )

    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec, limit=2000)

    agent = OpsAgent(sf)
    stores = [s.store_id for s in blast.affected_stores]
    assert len(stores) == 6
    for sid in stores:
        tasks = agent.generate_tasks(blast, scored, sid, recall_case_id=recall_case_id, recall_spec=recall_spec)
        assert 5 <= len(tasks) <= 15
        assert all(t.aisle.strip() and t.shelf.strip() for t in tasks)


def test_phase7_ops_agent_store4_fridge_mentions_deli_zone_and_quarantines_12_products(db_url, engine) -> None:
    from data_generator.seeds import store4_fridge_seed
    from backend.db.repositories import make_session_factory, RecallRepository

    _run_generator(db_url, "store4_fridge")

    with engine.begin() as conn:
        store_id = conn.execute(text("SELECT id FROM stores WHERE name = :n"), {"n": store4_fridge_seed.STORE_NAME}).scalar_one()

    sf = make_session_factory(engine)
    recall_case_id = RecallRepository(sf).create_recall_case()

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
        severity=Severity.high,
        hazard_type=HazardType.other,
        hazard_details="",
        symptom_timeline_days=(None, None),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )

    blast = TraceAgent(sf).build(recall_spec, store_id=uuid.UUID(str(store_id)), time_window=window)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    tasks = OpsAgent(sf).generate_tasks(blast, scored, uuid.UUID(str(store_id)), recall_case_id=recall_case_id, recall_spec=recall_spec)

    assert any("deli refrigeration zone" in t.description.lower() for t in tasks)
    assert sum(1 for t in tasks if t.task_type == TaskType.disposal_quarantine) == 12


def test_phase7_ops_agent_task_text_quality_specificity_score_high() -> None:
    from backend.agents.ops_agent import OpsAgent

    score = OpsAgent.grade_specificity(
        "Shelf pull: remove 'Sunny Valley Salsa Verde' (UPC 072440123456) from Aisle 3, Shelf 2; quarantine."
    )
    assert score >= 4


def test_phase7_ops_agent_escalation_ladder_updates_levels(db_url, engine) -> None:
    from backend.db.repositories import make_session_factory, RecallRepository

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)
    repo = RecallRepository(sf)
    rc_id = repo.create_recall_case()

    with engine.begin() as conn:
        store_id = conn.execute(text("SELECT id FROM stores ORDER BY name LIMIT 1")).scalar_one()

    # Insert an old open task for this store to trigger escalation.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO employee_tasks (id, recall_case_id, task_type, payload, status, created_at)
                VALUES (:id, :rc, 'shelf_pull', CAST(:p AS jsonb), 'open', :ts)
                """
            ),
            {
                "id": uuid.uuid4(),
                "rc": rc_id,
                "p": json.dumps({"store_id": str(store_id), "aisle": "Aisle 1", "shelf": "Shelf 1"}),
                "ts": datetime.now(tz=UTC) - timedelta(minutes=31),
            },
        )

    blast = {"affected_pallets": [], "affected_stores": [{"store_id": store_id, "affected_stock_fraction_peak": 1.0}], "affected_transactions_window": [], "affected_finished_product_ids": [], "inferred_facility_ids": {}}
    from backend.engine.recall_graph import BlastRadius as BlastRadiusModel

    blast_m = BlastRadiusModel.model_validate(blast)
    tasks = OpsAgent(sf).generate_tasks(blast_m, [], uuid.UUID(str(store_id)), recall_case_id=rc_id)
    # At least one task should pick up escalation level 1 for the matching aisle/shelf.
    assert any(t.escalation_level >= 1 for t in tasks)


def test_phase7_ops_agent_pos_block_created(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory, RecallRepository

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)
    rc_id = RecallRepository(sf).create_recall_case()

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
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )

    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec, limit=200)
    sid = blast.affected_stores[0].store_id
    OpsAgent(sf).generate_tasks(blast, scored, sid, recall_case_id=rc_id, recall_spec=recall_spec)

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT upc, lot_constraint FROM pos_blocks WHERE store_id = :sid"),
            {"sid": sid},
        ).all()
    assert any(r[0] == salsa_verde_seed.FINISHED_PRODUCT_UPC and salsa_verde_seed.INGREDIENT_LOT_CODE in (r[1] or "") for r in rows)


def test_phase7_ops_agent_determinism_same_inputs_same_structure(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)
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
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec, limit=500)
    sid = blast.affected_stores[0].store_id
    agent = OpsAgent(sf)
    a = [t.model_dump() for t in agent.generate_tasks(blast, scored, sid, recall_spec=recall_spec)]
    b = [t.model_dump() for t in agent.generate_tasks(blast, scored, sid, recall_spec=recall_spec)]
    assert a == b


def test_phase7_ops_agent_performance_all_6_stores_under_20s(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)
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
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec, limit=2000)
    agent = OpsAgent(sf)
    start = time.time()
    for s in blast.affected_stores:
        agent.generate_tasks(blast, scored, s.store_id, recall_spec=recall_spec)
    dur = time.time() - start
    assert dur < 20.0
