from __future__ import annotations

import subprocess
import time
from pathlib import Path


def _run_generate(db_url: str, seed: int, scenario: str, reset: bool) -> tuple[int, float, str]:
    repo_root = Path(__file__).resolve().parents[2]
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
    start = time.time()
    p = subprocess.run(cmd, check=False, capture_output=True, text=True)
    dur = time.time() - start
    return p.returncode, dur, (p.stdout + "\n" + p.stderr)


def test_generate_runs_under_60s_and_exits_0(db_url: str, engine) -> None:
    code, dur, out = _run_generate(db_url, seed=42, scenario="both", reset=True)
    assert code == 0, out
    assert dur < 60, f"took {dur:.2f}s"


def test_rerun_same_seed_produces_identical_counts(db_url: str, engine) -> None:
    code1, _, out1 = _run_generate(db_url, seed=42, scenario="both", reset=True)
    assert code1 == 0, out1
    # capture counts as lines "table: N"
    counts1 = {ln.split(":")[0].strip(): int(ln.split(":")[1]) for ln in out1.splitlines() if ":" in ln and ln.split(":")[1].strip().isdigit()}

    code2, _, out2 = _run_generate(db_url, seed=42, scenario="both", reset=True)
    assert code2 == 0, out2
    counts2 = {ln.split(":")[0].strip(): int(ln.split(":")[1]) for ln in out2.splitlines() if ":" in ln and ln.split(":")[1].strip().isdigit()}

    assert counts1 == counts2

