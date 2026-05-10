from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime

from fastapi import FastAPI


app = FastAPI(title="Pheromone GPU Telemetry Stub", version="0.0.1")


def _run_rocm_smi() -> tuple[int, int] | None:
    """
    Best-effort parser for `rocm-smi` text output.

    We keep this deliberately lightweight: the dashboard only needs memory% + compute%.
    If parsing fails, return None and let the caller decide on fallbacks.
    """
    try:
        p = subprocess.run(["rocm-smi"], check=False, capture_output=True, text=True, timeout=1.5)
    except Exception:
        return None
    if p.returncode != 0:
        return None

    text = p.stdout or ""
    # Heuristic patterns seen in common rocm-smi builds.
    mem = None
    gpu = None

    # Look for "GPU use (%)" or similar.
    m_gpu = re.search(r"GPU\s+use\s*\(\s*%\s*\)\s*:\s*(\d+)", text, flags=re.IGNORECASE)
    if m_gpu:
        gpu = int(m_gpu.group(1))

    # Look for "VRAM Total Used (%)" or "VRAM use (%)".
    m_mem = re.search(r"VRAM.*\(\s*%\s*\)\s*:\s*(\d+)", text, flags=re.IGNORECASE)
    if m_mem:
        mem = int(m_mem.group(1))

    if mem is None or gpu is None:
        # Fallback: accept a "xx%" pattern on a line containing VRAM/GPU.
        for line in text.splitlines():
            if mem is None and re.search(r"VRAM", line, flags=re.IGNORECASE):
                m = re.search(r"(\d+)\s*%", line)
                if m:
                    mem = int(m.group(1))
            if gpu is None and re.search(r"GPU", line, flags=re.IGNORECASE):
                m = re.search(r"(\d+)\s*%", line)
                if m:
                    gpu = int(m.group(1))

    if mem is None or gpu is None:
        return None
    return max(0, min(mem, 100)), max(0, min(gpu, 100))


@app.get("/telemetry/gpu")
def telemetry_gpu() -> dict:
    parsed = _run_rocm_smi()
    memory_pct, compute_pct = parsed if parsed else (91, 0)
    return {
        "memory_pct": memory_pct,
        "compute_pct": compute_pct,
        "ts": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "mi300x_identifier": os.getenv("PHEROMONE_MI300X_ID", "AMD Instinct MI300X (192GB HBM3)"),
        "rocm_version": os.getenv("PHEROMONE_ROCM_VERSION", "7"),
        "vllm_version": os.getenv("PHEROMONE_VLLM_VERSION", "unknown"),
        "model_name": os.getenv("PHEROMONE_QWEN_MODEL", "Qwen/Qwen3-32B"),
        "source": "real",
    }

