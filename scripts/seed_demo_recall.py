from __future__ import annotations

# Self-bootstrapping import path so this script works when invoked as:
# - `./.venv/bin/python scripts/seed_demo_recall.py`
# - `python -m scripts.seed_demo_recall`
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import os
import subprocess
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.agents.intake_agent import ExtractedString, HazardType, RecallSpec as IntakeRecallSpec
from backend.db.db_url import DEFAULT_DATABASE_URL


def _run_generator(db_url: str, *, seed: int, scenario: str, reset: bool) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        str(repo_root / ".venv" / "bin" / "python"),
        str(repo_root / "data_generator" / "generate.py"),
        "--db-url",
        db_url,
        "--seed",
        str(seed),
        "--scenario",
        scenario,
    ]
    if reset:
        cmd.append("--reset")
    p = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"data_generator failed\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")


def _poll_state(client: TestClient, recall_case_id: str, *, want: str, timeout_s: float) -> dict:
    start = time.time()
    last = None
    while time.time() - start < timeout_s:
        r = client.get(f"/recalls/{recall_case_id}")
        if r.status_code != 200:
            raise RuntimeError(f"GET /recalls/{recall_case_id} -> {r.status_code}: {r.text}")
        last = r.json()
        if last.get("state") == want:
            return last
        time.sleep(0.25)
    raise RuntimeError(f"timeout waiting for state={want}; last={last}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the Salsa-Verde demo recall (persisted in Postgres).")
    ap.add_argument("--db-url", default=(os.getenv("DATABASE_URL") or "").strip(), help="Postgres DATABASE_URL")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset", action="store_true", help="Reset DB before generating scenario data")
    args = ap.parse_args()

    db_url = (args.db_url or "").strip()
    if not db_url:
        db_url = DEFAULT_DATABASE_URL
        print(f"[seed] No DATABASE_URL set; using default {DEFAULT_DATABASE_URL}")

    os.environ["DATABASE_URL"] = db_url

    from data_generator.seeds import salsa_verde_seed

    _run_generator(db_url, seed=args.seed, scenario="salsa_verde", reset=bool(args.reset))

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
        raw_notice_text="Salsa-Verde seeded recall (demo).",
    ).model_dump(mode="json")

    res = client.post(
        "/recalls",
        json={
            "source_type": "supplier",
            "external_id": "RG-4429",
            "raw_text": "Salsa-Verde recall seed (demo)",
            "recall_spec": spec,
        },
    )
    if res.status_code != 200:
        raise RuntimeError(f"POST /recalls failed: {res.status_code} {res.text}")
    rid = res.json()["recall_case_id"]

    _poll_state(client, rid, want="awaiting_manager_approval", timeout_s=120)
    ok = client.post(f"/recalls/{rid}/approve_batch", json={"approved_by": "manager@example.com"})
    if ok.status_code != 200:
        raise RuntimeError(f"approve_batch failed: {ok.status_code} {ok.text}")
    _poll_state(client, rid, want="closed", timeout_s=120)

    print(rid)


if __name__ == "__main__":
    main()
