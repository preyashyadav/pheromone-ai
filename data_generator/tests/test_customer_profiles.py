from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import text


def test_customer_profile_consistency_preferred_store(db_url: str, engine) -> None:
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
            "none",
            "--reset",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr

    with engine.begin() as conn:
        customer_ids = conn.execute(
            text("SELECT id FROM customers ORDER BY id LIMIT 20")
        ).scalars().all()
        assert len(customer_ids) == 20

        for cid in customer_ids:
            preferred = conn.execute(
                text("SELECT (profile->>'preferred_store_id')::uuid FROM customers WHERE id = :cid"),
                {"cid": cid},
            ).scalar_one()
            total = conn.execute(
                text("SELECT COUNT(*) FROM pos_transactions WHERE customer_id = :cid"),
                {"cid": cid},
            ).scalar_one()
            if int(total) == 0:
                continue
            at_pref = conn.execute(
                text("SELECT COUNT(*) FROM pos_transactions WHERE customer_id = :cid AND store_id = :sid"),
                {"cid": cid, "sid": preferred},
            ).scalar_one()
            assert (int(at_pref) / int(total)) > 0.70

