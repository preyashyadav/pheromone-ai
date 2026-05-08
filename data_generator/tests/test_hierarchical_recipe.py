from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import text


def test_hierarchical_recipe_seasoning_blend_exists_and_used(db_url: str, engine) -> None:
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
        blend_id = conn.execute(
            text("SELECT id FROM ingredients WHERE name = 'seasoning_blend_X'")
        ).scalar_one()
        child_count = conn.execute(
            text("SELECT COUNT(*) FROM ingredients WHERE parent_ingredient_id = :pid"),
            {"pid": blend_id},
        ).scalar_one()
        assert int(child_count) >= 3

        used_count = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM finished_products fp,
                LATERAL jsonb_array_elements(fp.ingredient_recipe) e
                WHERE (e->>'ingredient_id')::uuid = :blend_id
                """
            ),
            {"blend_id": blend_id},
        ).scalar_one()
        assert int(used_count) >= 5

