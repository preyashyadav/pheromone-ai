from __future__ import annotations

import os
import subprocess
import time
import uuid
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from backend.orchestration.graph import sse_events
from sqlalchemy import text

from backend.api.main import app
from backend.agents.intake_agent import ExtractedString, HazardType, RecallSpec as IntakeRecallSpec


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


def _poll_state(client: TestClient, recall_case_id: str, *, want: str, timeout_s: float) -> dict:
    start = time.time()
    last = None
    while time.time() - start < timeout_s:
        r = client.get(f"/recalls/{recall_case_id}")
        assert r.status_code == 200
        last = r.json()
        if last.get("state") == want:
            return last
        time.sleep(0.25)
    raise AssertionError(f"timeout waiting for state={want}; last={last}")


def test_phase9_end_to_end_salsa_verde_pause_resume_performance_and_idempotency(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed

    _run_generator(db_url, "salsa_verde")
    client = TestClient(app)

    spec = IntakeRecallSpec(
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
        extraction_confidence={"product_identifiers": 0.7, "hazard_type": 0.7, "severity": 0.7},
        raw_notice_text="",
    ).model_dump(mode="json")

    t0 = time.time()
    res = client.post(
        "/recalls",
        json={
            "source_type": "supplier",
            "external_id": "RG-4429",
            "raw_text": "Salsa-Verde recall seed",
            "recall_spec": spec,
        },
    )
    assert res.status_code == 200
    rid = res.json()["recall_case_id"]

    _poll_state(client, rid, want="awaiting_manager_approval", timeout_s=90)
    assert (time.time() - t0) < 90.0

    # Idempotency: POSTing again should not add duplicate tasks/drafts.
    with engine.begin() as conn:
        tasks_before = int(conn.execute(text("SELECT count(*) FROM employee_tasks WHERE recall_case_id = :id"), {"id": rid}).scalar_one())
        drafts_before = int(conn.execute(text("SELECT count(*) FROM notification_drafts WHERE recall_case_id = :id"), {"id": rid}).scalar_one())

    res2 = client.post(
        "/recalls",
        json={
            "source_type": "supplier",
            "external_id": "RG-4429",
            "raw_text": "Salsa-Verde recall seed",
            "recall_spec": spec,
        },
    )
    assert res2.status_code == 200
    assert res2.json()["recall_case_id"] == rid

    # Allow any queued runner to attempt; should not duplicate due to guards.
    time.sleep(2.0)
    with engine.begin() as conn:
        tasks_after = int(conn.execute(text("SELECT count(*) FROM employee_tasks WHERE recall_case_id = :id"), {"id": rid}).scalar_one())
        drafts_after = int(conn.execute(text("SELECT count(*) FROM notification_drafts WHERE recall_case_id = :id"), {"id": rid}).scalar_one())

    assert tasks_after == tasks_before
    assert drafts_after == drafts_before

    # Approve and finish.
    ok = client.post(f"/recalls/{rid}/approve_batch", json={"approved_by": "manager@example.com"})
    assert ok.status_code == 200
    _poll_state(client, rid, want="closed", timeout_s=60)


def test_phase9_crash_recovery_resumes_from_match_running_without_redoing_intake_trace(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed

    _run_generator(db_url, "salsa_verde")
    client = TestClient(app)

    spec = IntakeRecallSpec(
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
        extraction_confidence={"product_identifiers": 0.7, "hazard_type": 0.7, "severity": 0.7},
        raw_notice_text="",
    ).model_dump(mode="json")

    os.environ["PHEROMONE_TEST_CRASH_MATCH_ONCE"] = "1"
    try:
        res = client.post(
            "/recalls",
            json={"source_type": "supplier", "external_id": "RG-4429-crash", "raw_text": "crash", "recall_spec": spec},
        )
        assert res.status_code == 200
        rid = res.json()["recall_case_id"]

        _poll_state(client, rid, want="match_running", timeout_s=60)
        with engine.begin() as conn:
            spec_count = int(conn.execute(text("SELECT count(*) FROM recall_specs WHERE recall_case_id = :id"), {"id": rid}).scalar_one())
            blast_count = int(conn.execute(text("SELECT count(*) FROM affected_blast_radius_snapshots WHERE recall_case_id = :id"), {"id": rid}).scalar_one())
        assert spec_count == 1
        assert blast_count == 1

        # "Restart": call POST again (idempotent), which should resume and complete Match.
        res2 = client.post(
            "/recalls",
            json={"source_type": "supplier", "external_id": "RG-4429-crash", "raw_text": "crash", "recall_spec": spec},
        )
        assert res2.status_code == 200
        assert res2.json()["recall_case_id"] == rid

        _poll_state(client, rid, want="awaiting_manager_approval", timeout_s=90)
        with engine.begin() as conn:
            spec_count2 = int(conn.execute(text("SELECT count(*) FROM recall_specs WHERE recall_case_id = :id"), {"id": rid}).scalar_one())
            blast_count2 = int(conn.execute(text("SELECT count(*) FROM affected_blast_radius_snapshots WHERE recall_case_id = :id"), {"id": rid}).scalar_one())
        assert spec_count2 == 1
        assert blast_count2 == 1
    finally:
        os.environ.pop("PHEROMONE_TEST_CRASH_MATCH_ONCE", None)


@pytest.mark.asyncio
async def test_phase9_streaming_sse_emits_events_per_agent_transition(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed

    _run_generator(db_url, "salsa_verde")
    client = TestClient(app)

    spec = IntakeRecallSpec(
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
        extraction_confidence={"product_identifiers": 0.7, "hazard_type": 0.7, "severity": 0.7},
        raw_notice_text="",
    ).model_dump(mode="json")

    res = client.post("/recalls", json={"source_type": "supplier", "external_id": "RG-4429-stream", "raw_text": "sse", "recall_spec": spec})
    rid = res.json()["recall_case_id"]

    seen_nodes: set[str] = set()
    import asyncio

    async def _collect_for(seconds: float) -> None:
        start = time.time()
        async for chunk in sse_events(uuid.UUID(rid), keepalive_s=1.0):
            if time.time() - start > seconds:
                break
            try:
                text_chunk = chunk.decode("utf-8", errors="ignore")
            except Exception:
                continue
            for line in text_chunk.splitlines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :].strip()
                if payload == "{}":
                    continue
                try:
                    obj = json.loads(payload)
                except Exception:
                    continue
                node = str(obj.get("node") or "")
                if node:
                    seen_nodes.add(node)
            if {"intake", "trace", "match"}.issubset(seen_nodes):
                break

    await asyncio.wait_for(_collect_for(30.0), timeout=40.0)

    # At least one transition event per agent node.
    assert {"intake", "trace", "match"}.issubset(seen_nodes)


def test_phase9_low_confidence_routes_to_scope_review_pause(db_url, engine) -> None:
    _run_generator(db_url, "salsa_verde")
    client = TestClient(app)

    spec = IntakeRecallSpec(
        recall_id="LOWCONF",
        source_type="supplier",
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
        extraction_confidence={"product_identifiers": 0.5, "hazard_type": 0.55, "severity": 0.5},
        raw_notice_text="",
    ).model_dump(mode="json")

    res = client.post("/recalls", json={"source_type": "supplier", "external_id": "LOWCONF", "raw_text": "lowconf", "recall_spec": spec})
    rid = res.json()["recall_case_id"]
    _poll_state(client, rid, want="scope_review_pending", timeout_s=30)


def test_phase9_scope_change_reruns_match_for_new_transactions_only(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed

    _run_generator(db_url, "salsa_verde")
    client = TestClient(app)

    spec = IntakeRecallSpec(
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
        extraction_confidence={"product_identifiers": 0.7, "hazard_type": 0.7, "severity": 0.7},
        raw_notice_text="",
    ).model_dump(mode="json")

    res = client.post("/recalls", json={"source_type": "supplier", "external_id": "RG-4429-scope", "raw_text": "scope", "recall_spec": spec})
    rid = res.json()["recall_case_id"]
    _poll_state(client, rid, want="awaiting_manager_approval", timeout_s=90)

    with engine.begin() as conn:
        before = int(conn.execute(text("SELECT count(*) FROM scored_transactions WHERE recall_case_id = :id"), {"id": rid}).scalar_one())
        # Pick a transaction not already scored (simulate scope expansion).
        new_tx = conn.execute(
            text(
                "SELECT id FROM pos_transactions WHERE id NOT IN (SELECT transaction_id FROM scored_transactions WHERE recall_case_id = :id) LIMIT 1"
            ),
            {"id": rid},
        ).scalar_one()
        assert new_tx is not None

    res2 = client.post(
        "/recalls",
        json={
            "source_type": "supplier",
            "external_id": "RG-4429-scope",
            "raw_text": "scope",
            "recall_spec": spec,
            "scope_override_transaction_ids": [str(uuid.UUID(str(new_tx)))],
        },
    )
    assert res2.status_code == 200
    assert res2.json()["recall_case_id"] == rid

    # Wait for delta scoring to land.
    start = time.time()
    while time.time() - start < 30:
        with engine.begin() as conn:
            after = int(conn.execute(text("SELECT count(*) FROM scored_transactions WHERE recall_case_id = :id"), {"id": rid}).scalar_one())
        if after == before + 1:
            break
        time.sleep(0.25)
    assert after == before + 1
