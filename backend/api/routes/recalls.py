from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text

from backend.agents.intake_agent import RecallSpec as IntakeRecallSpec
from backend.db.repositories import (
    CustomerRepository,
    InventoryRepository,
    RecallRepository,
    Repositories,
    SupplyChainRepository,
    make_session_factory,
)
from backend.orchestration.graph import (
    sse_events,
    start_or_resume_recall,
    resume_from_interrupt,
    score_scope_delta,
)
from backend.db.db_url import DEFAULT_DATABASE_URL, get_database_url


router = APIRouter(prefix="/recalls", tags=["recalls"])


def _db_url() -> str:
    # Dashboard/local dev convenience: default to a predictable local Postgres when env is unset.
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


class RecallSubmitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["openfda", "usda_fsis", "supplier", "retailer_internal"] = "supplier"
    external_id: str | None = None
    source_url: str | None = None
    published_at_utc: datetime | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""

    # Optional: provide a structured Intake RecallSpec (used in Phase 9 tests).
    recall_spec: dict[str, Any] | None = None

    # Optional: simulate scope expansion by providing a superset of affected transaction ids.
    scope_override_transaction_ids: list[str] | None = None


class RecallSubmitOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recall_case_id: str
    created: bool


class RecallGetOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recall_case_id: str
    state: str
    source_type: str | None
    source_details: dict[str, Any]
    recall_spec: dict[str, Any] | None


def _dedupe_key(inp: RecallSubmitIn) -> str:
    if inp.external_id:
        return f"{inp.source_type}:{inp.external_id}"
    content = json.dumps(
        {"source_type": inp.source_type, "source_url": inp.source_url, "raw_json": inp.raw_json, "raw_text": inp.raw_text},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@router.post("", response_model=RecallSubmitOut)
def submit_recall(inp: RecallSubmitIn) -> RecallSubmitOut:
    repos = _repos()
    dedupe = _dedupe_key(inp)
    existing = repos.recalls.find_recall_case_by_dedupe_key(dedupe_key=dedupe)
    created = False

    if existing is None:
        recall_case_id = repos.recalls.create_recall_case_signal_detected(
            source_type=inp.source_type,
            store_id=None,
            source_details={
                "dedupe_key": dedupe,
                "source_url": inp.source_url,
                "external_id": inp.external_id,
                "published_at_utc": (inp.published_at_utc or datetime.now(tz=UTC)).isoformat().replace("+00:00", "Z"),
            },
        )
        created = True
    else:
        recall_case_id = existing

    provided_spec = None
    if inp.recall_spec is not None:
        # Validate shape early.
        provided_spec = IntakeRecallSpec.model_validate(inp.recall_spec).model_dump(mode="json")

    # Run orchestration asynchronously.
    threading.Thread(
        target=start_or_resume_recall,
        kwargs={
            "recall_case_id": recall_case_id,
            "provided_spec": provided_spec,
            "scope_override_transaction_ids": inp.scope_override_transaction_ids,
        },
        daemon=True,
    ).start()

    # If this is a "scope expansion" resubmission, force a re-run of match+downstream by time-traveling
    # from the trace successor.
    if (not created) and inp.scope_override_transaction_ids:
        threading.Thread(
            target=score_scope_delta,
            kwargs={"recall_case_id": recall_case_id, "transaction_ids": inp.scope_override_transaction_ids},
            daemon=True,
        ).start()

    return RecallSubmitOut(recall_case_id=str(recall_case_id), created=created)


@router.get("/{recall_case_id}", response_model=RecallGetOut)
def get_recall(recall_case_id: str) -> RecallGetOut:
    repos = _repos()
    try:
        rid = uuid.UUID(recall_case_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid recall_case_id")
    rc = repos.recalls.get_recall_case(rid)
    if rc is None:
        raise HTTPException(status_code=404, detail="not found")
    spec = repos.recalls.get_recall_spec(recall_case_id=rid)
    return RecallGetOut(
        recall_case_id=str(rc.id),
        state=str(rc.state.value),
        source_type=rc.source_type,
        source_details=rc.source_details or {},
        recall_spec=spec,
    )


@router.get("/{recall_case_id}/stream")
def stream_recall(recall_case_id: str) -> StreamingResponse:
    try:
        rid = uuid.UUID(recall_case_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid recall_case_id")
    return StreamingResponse(sse_events(rid), media_type="text/event-stream")


class ManagerActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = "manager@example.com"


@router.post("/{recall_case_id}/approve_batch")
def approve_batch(recall_case_id: str, _: ManagerActionIn) -> dict[str, str]:
    try:
        rid = uuid.UUID(recall_case_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid recall_case_id")
    threading.Thread(
        target=resume_from_interrupt,
        kwargs={"recall_case_id": rid, "resume_value": "approved"},
        daemon=True,
    ).start()
    return {"status": "ok"}


@router.post("/{recall_case_id}/reject_batch")
def reject_batch(recall_case_id: str, _: ManagerActionIn) -> dict[str, str]:
    try:
        rid = uuid.UUID(recall_case_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid recall_case_id")
    threading.Thread(
        target=resume_from_interrupt,
        kwargs={"recall_case_id": rid, "resume_value": "rejected"},
        daemon=True,
    ).start()
    return {"status": "ok"}
