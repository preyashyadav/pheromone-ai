from __future__ import annotations

from sqlalchemy import text


def _count(engine, table: str) -> int:
    with engine.begin() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def test_row_counts_in_expected_ranges(db_url: str, engine) -> None:
    # generation happens in test_phase2_runs via subprocess; run it here too for isolation
    import subprocess
    from pathlib import Path

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
            "both",
            "--reset",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr

    assert _count(engine, "suppliers") == 8
    assert _count(engine, "ingredients") == 35
    assert _count(engine, "manufacturers") == 4
    assert _count(engine, "facilities") == 8
    assert _count(engine, "distributors") == 2
    assert _count(engine, "distributor_warehouses") == 4
    assert _count(engine, "stores") == 8
    assert _count(engine, "finished_products") == 60

    assert 300 <= _count(engine, "ingredient_lots") <= 310
    assert 500 <= _count(engine, "production_runs") <= 520
    assert 1500 <= _count(engine, "finished_product_lots") <= 1520
    assert 8000 <= _count(engine, "pallets") <= 8200
    assert 700 <= _count(engine, "shipments") <= 720
    assert 3000 <= _count(engine, "store_shipments") <= 3100
    assert _count(engine, "stocking_events") >= 6000

    assert _count(engine, "customers") == 2000
    assert _count(engine, "institutional_accounts") == 15
    assert _count(engine, "pos_transactions") >= 15000

