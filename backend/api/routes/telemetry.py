from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine

from backend.db.repositories import (
    CustomerRepository,
    InventoryRepository,
    RecallRepository,
    Repositories,
    SupplyChainRepository,
    make_session_factory,
)
from backend.db.db_url import DEFAULT_DATABASE_URL, get_database_url


router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


def _db_url() -> str:
    url = get_database_url()
    if url == DEFAULT_DATABASE_URL and not (os.environ.get("DATABASE_URL") or "").strip():
        print(f"[db] No DATABASE_URL set; using default {DEFAULT_DATABASE_URL}")
    return url


_ENGINE = None
_ENGINE_URL = None
_ENGINE_LOCK = threading.Lock()


def _repos() -> Repositories:
    global _ENGINE, _ENGINE_URL
    with _ENGINE_LOCK:
        url = _db_url()
        if _ENGINE is None or _ENGINE_URL != url:
            _ENGINE = create_engine(url, pool_pre_ping=True)
            _ENGINE_URL = url
    sf = make_session_factory(_ENGINE)
    return Repositories(
        supply_chain=SupplyChainRepository(sf),
        inventory=InventoryRepository(sf),
        customers=CustomerRepository(sf),
        recalls=RecallRepository(sf),
    )


class AgentTelemetryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    state: str
    latency_ms: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    ts: str


class AgentsTelemetryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recall_case_id: str | None = None
    recall_state: str | None = None
    agents: list[AgentTelemetryRow] = Field(default_factory=list)


@router.get("/agents", response_model=AgentsTelemetryOut)
def get_agents_telemetry() -> AgentsTelemetryOut:
    repos = _repos()
    cases = repos.recalls.list_recall_cases_minimal(limit=1)
    if not cases:
        return AgentsTelemetryOut()

    rc = cases[0]
    recall_case_id = uuid.UUID(str(rc["recall_case_id"]))
    events = repos.recalls.list_compliance_events(recall_case_id=recall_case_id, limit=500)

    latest_by_agent: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.get("event_type") != "agent_metrics":
            continue
        payload = e.get("payload") or {}
        agent = str(payload.get("agent") or "")
        if not agent:
            continue
        latest_by_agent[agent] = payload

    agents: list[AgentTelemetryRow] = []
    for agent, payload in sorted(latest_by_agent.items(), key=lambda kv: kv[0]):
        agents.append(
            AgentTelemetryRow(
                agent=agent,
                state=str(payload.get("state") or ""),
                latency_ms=int(payload.get("latency_ms") or 0),
                tokens_in=int(payload.get("tokens_in") or 0),
                tokens_out=int(payload.get("tokens_out") or 0),
                ts=str(payload.get("ts") or ""),
            )
        )

    return AgentsTelemetryOut(
        recall_case_id=str(recall_case_id),
        recall_state=str(rc.get("state") or ""),
        agents=agents,
    )


class GpuTelemetryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_pct: int = Field(ge=0, le=100)
    compute_pct: int = Field(ge=0, le=100)
    ts: str

    mi300x_identifier: str
    rocm_version: str
    vllm_version: str
    model_name: str

    source: str


_GPU_CACHE_LOCK = threading.Lock()
_GPU_CACHE: tuple[float, dict[str, Any]] | None = None


def _mock_gpu(*, busy: bool) -> dict[str, Any]:
    # "Realistic" values that tell the AMD story even when the droplet is down.
    return {
        "memory_pct": 91,
        "compute_pct": (90 if busy else 0),
        "mi300x_identifier": os.getenv("PHEROMONE_MI300X_ID", "AMD Instinct MI300X (192GB HBM3)"),
        "rocm_version": os.getenv("PHEROMONE_ROCM_VERSION", "7"),
        "vllm_version": os.getenv("PHEROMONE_VLLM_VERSION", "unknown"),
        "model_name": os.getenv("PHEROMONE_QWEN_MODEL", "Qwen/Qwen3-32B"),
        "source": "mock",
    }


def _fetch_gpu_real(endpoint: str) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=httpx.Timeout(2.0)) as client:
            r = client.get(endpoint)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                return None
            return data
    except Exception:
        return None


@router.get("/gpu", response_model=GpuTelemetryOut)
def get_gpu_telemetry() -> GpuTelemetryOut:
    endpoint = (os.getenv("PHEROMONE_GPU_ENDPOINT") or "").strip()
    now = time.time()
    with _GPU_CACHE_LOCK:
        global _GPU_CACHE
        if _GPU_CACHE is not None:
            cached_at, cached = _GPU_CACHE
            if (now - cached_at) <= 5.0:
                data = dict(cached)
                data["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                return GpuTelemetryOut.model_validate(data)

    data: dict[str, Any] | None = None
    if endpoint:
        data = _fetch_gpu_real(endpoint)

    if not data:
        # Busy heuristic: if we recently logged agent metrics, show "busy".
        repos = _repos()
        cases = repos.recalls.list_recall_cases_minimal(limit=1)
        busy = False
        if cases:
            rid = uuid.UUID(str(cases[0]["recall_case_id"]))
            events = repos.recalls.list_compliance_events(recall_case_id=rid, limit=50)
            for e in reversed(events):
                if e.get("event_type") == "agent_metrics":
                    busy = True
                    break
        data = _mock_gpu(busy=busy)

    # Normalize and cache.
    out = {
        "memory_pct": int(data.get("memory_pct") or 0),
        "compute_pct": int(data.get("compute_pct") or 0),
        "mi300x_identifier": str(
            data.get("mi300x_identifier") or os.getenv("PHEROMONE_MI300X_ID", "AMD Instinct MI300X (192GB HBM3)")
        ),
        "rocm_version": str(data.get("rocm_version") or os.getenv("PHEROMONE_ROCM_VERSION", "7")),
        "vllm_version": str(data.get("vllm_version") or os.getenv("PHEROMONE_VLLM_VERSION", "unknown")),
        "model_name": str(data.get("model_name") or os.getenv("PHEROMONE_QWEN_MODEL", "Qwen/Qwen3-32B")),
        "source": str(data.get("source") or ("real" if endpoint else "mock")),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    with _GPU_CACHE_LOCK:
        _GPU_CACHE = (now, dict(out))
    try:
        return GpuTelemetryOut.model_validate(out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"invalid gpu telemetry payload: {e}")
