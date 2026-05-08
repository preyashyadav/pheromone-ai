from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import text

from data_generator.seeds import store4_fridge_seed


def test_store4_fridge_seed_verification(db_url: str, engine) -> None:
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
            "store4_fridge",
            "--reset",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr

    with engine.begin() as conn:
        zone_id = conn.execute(
            text(
                """
                SELECT z.id
                FROM refrigeration_zones z
                JOIN stores s ON s.id = z.store_id
                WHERE s.name = :store_name AND z.name = :zone_name
                """
            ),
            {"store_name": store4_fridge_seed.STORE_NAME, "zone_name": store4_fridge_seed.ZONE_NAME},
        ).scalar_one()

        failure_count = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM refrigeration_events
                WHERE zone_id = :zone_id
                  AND event_type = 'failure'
                  AND timestamp = :ts
                """
            ),
            {"zone_id": zone_id, "ts": store4_fridge_seed.FAILURE_AT_UTC},
        ).scalar_one()
        assert int(failure_count) == 1

        restored_count = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM refrigeration_events
                WHERE zone_id = :zone_id
                  AND event_type = 'restored'
                  AND timestamp = :ts
                """
            ),
            {"zone_id": zone_id, "ts": store4_fridge_seed.RESTORED_AT_UTC},
        ).scalar_one()
        assert int(restored_count) == 1

        store4_id = conn.execute(text("SELECT id FROM stores WHERE name = :n"), {"n": store4_fridge_seed.STORE_NAME}).scalar_one()
        tx_count = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM pos_transactions t
                WHERE t.store_id = :store_id
                  AND t.timestamp >= :start
                  AND t.timestamp <= :end
                """
            ),
            {"store_id": store4_id, "start": store4_fridge_seed.FAILURE_AT_UTC, "end": store4_fridge_seed.DISCOVERED_AT_UTC},
        ).scalar_one()
        assert int(tx_count) >= 50

