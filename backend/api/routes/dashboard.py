from __future__ import annotations

import os
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text

from backend.db.repositories import (
    CustomerRepository,
    InventoryRepository,
    RecallRepository,
    Repositories,
    SupplyChainRepository,
    make_session_factory,
)
from backend.db.db_url import DEFAULT_DATABASE_URL, get_database_url


router = APIRouter(prefix="/api", tags=["dashboard"])


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


def _as_uuid(v: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid id")


def _initials(name: str) -> str:
    parts = [p for p in (name or "").strip().split() if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def _mask_email(email: str) -> str:
    if "@" not in (email or ""):
        return ""
    local, domain = email.split("@", 1)
    if not local:
        return f"*@{domain}"
    return f"{local[:1]}***@{domain}"


class RecallFeedRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recall_case_id: str
    state: str
    source_type: str | None = None
    updated_at_utc: str
    severity: str | None = None
    hazard_type: str | None = None
    recall_id: str | None = None


class RecallFeedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recalls: list[RecallFeedRow] = Field(default_factory=list)


@router.get("/recalls", response_model=RecallFeedOut)
def list_recalls(limit: int = 50) -> RecallFeedOut:
    repos = _repos()
    rows = repos.recalls.list_recall_cases_minimal(limit=limit)
    out: list[RecallFeedRow] = []
    for r in rows:
        updated = r.get("updated_at")
        if isinstance(updated, datetime):
            updated_s = updated.astimezone(UTC).isoformat().replace("+00:00", "Z")
        else:
            updated_s = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        out.append(
            RecallFeedRow(
                recall_case_id=str(r["recall_case_id"]),
                state=str(r.get("state") or ""),
                source_type=(str(r.get("source_type")) if r.get("source_type") is not None else None),
                updated_at_utc=updated_s,
                severity=(str(r.get("severity")) if r.get("severity") is not None else None),
                hazard_type=(str(r.get("hazard_type")) if r.get("hazard_type") is not None else None),
                recall_id=(str(r.get("recall_id")) if r.get("recall_id") is not None else None),
            )
        )
    return RecallFeedOut(recalls=out)


class RecallOverviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recall_case_id: str
    state: str
    source_type: str | None = None
    source_details: dict[str, Any] = Field(default_factory=dict)
    recall_spec: dict[str, Any] | None = None


@router.get("/recalls/{recall_case_id}/overview", response_model=RecallOverviewOut)
def recall_overview(recall_case_id: str) -> RecallOverviewOut:
    repos = _repos()
    rid = _as_uuid(recall_case_id)
    rc = repos.recalls.get_recall_case(rid)
    if rc is None:
        raise HTTPException(status_code=404, detail="not found")
    spec = repos.recalls.get_recall_spec(recall_case_id=rid)
    return RecallOverviewOut(
        recall_case_id=str(rid),
        state=str(rc.state.value),
        source_type=rc.source_type,
        source_details=rc.source_details or {},
        recall_spec=spec,
    )


class BlastRadiusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blast_radius: dict[str, Any] | None = None


@router.get("/recalls/{recall_case_id}/blast_radius", response_model=BlastRadiusOut)
def recall_blast_radius(recall_case_id: str) -> BlastRadiusOut:
    repos = _repos()
    rid = _as_uuid(recall_case_id)
    blast = repos.recalls.get_latest_blast_radius_snapshot(recall_case_id=rid)
    return BlastRadiusOut(blast_radius=blast)


class TransactionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    store_id: str
    timestamp_utc: str
    affected_probability: float = Field(ge=0.0, le=1.0)
    confidence_tier: str
    customer_initials: str | None = None
    email_masked: str | None = None


class TransactionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transactions: list[TransactionRow] = Field(default_factory=list)


@router.get("/recalls/{recall_case_id}/transactions", response_model=TransactionsOut)
def recall_transactions(recall_case_id: str, limit: int = 2000) -> TransactionsOut:
    rid = _as_uuid(recall_case_id)
    limit = max(1, min(int(limit), 5000))
    repos = _repos()
    # Typed repo layer is used for inserts; for this dashboard read path, a single SQL join is simpler.
    sf = repos.recalls._session_factory  # noqa: SLF001
    with sf() as s:
        rows = s.execute(
            text(
                """
                SELECT st.transaction_id,
                       st.affected_probability,
                       st.details,
                       tx.store_id,
                       tx.timestamp,
                       c.profile
                FROM scored_transactions st
                JOIN pos_transactions tx ON tx.id = st.transaction_id
                LEFT JOIN customers c ON c.id = tx.customer_id
                WHERE st.recall_case_id = :rid
                ORDER BY tx.timestamp DESC
                LIMIT :lim
                """
            ),
            {"rid": rid, "lim": limit},
        ).all()

    out: list[TransactionRow] = []
    for tx_id, affected_prob_milli, details, store_id, ts, profile in rows:
        d = details if isinstance(details, dict) else {}
        tier = str(d.get("confidence_tier") or "")
        name = ""
        email = ""
        if isinstance(profile, dict):
            name = str(profile.get("name") or "")
            email = str(profile.get("email") or "")
        out.append(
            TransactionRow(
                transaction_id=str(tx_id),
                store_id=str(store_id),
                timestamp_utc=ts.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                affected_probability=float(int(affected_prob_milli or 0) / 1000.0),
                confidence_tier=tier,
                customer_initials=_initials(name) if name else None,
                email_masked=_mask_email(email) if email else None,
            )
        )
    return TransactionsOut(transactions=out)


class TaskRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task_type: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at_utc: str


class TasksOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskRow] = Field(default_factory=list)


@router.get("/recalls/{recall_case_id}/tasks", response_model=TasksOut)
def recall_tasks(recall_case_id: str) -> TasksOut:
    repos = _repos()
    rid = _as_uuid(recall_case_id)
    rows = repos.recalls.list_employee_tasks_minimal(recall_case_id=rid)
    out: list[TaskRow] = []
    for r in rows:
        created = r.get("created_at")
        if isinstance(created, datetime):
            created_s = created.astimezone(UTC).isoformat().replace("+00:00", "Z")
        else:
            created_s = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        out.append(
            TaskRow(
                id=str(r["id"]),
                task_type=str(r.get("task_type") or ""),
                status=str(r.get("status") or ""),
                payload=(r.get("payload") if isinstance(r.get("payload"), dict) else {}),
                created_at_utc=created_s,
            )
        )
    return TasksOut(tasks=out)


class DraftRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    channel: str
    confidence_tier: str
    draft: dict[str, Any] = Field(default_factory=dict)
    created_at_utc: str


class DraftsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drafts: list[DraftRow] = Field(default_factory=list)


@router.get("/recalls/{recall_case_id}/drafts", response_model=DraftsOut)
def recall_drafts(recall_case_id: str) -> DraftsOut:
    repos = _repos()
    rid = _as_uuid(recall_case_id)
    rows = repos.recalls.list_notification_drafts_minimal(recall_case_id=rid)
    out: list[DraftRow] = []
    for r in rows:
        created = r.get("created_at")
        if isinstance(created, datetime):
            created_s = created.astimezone(UTC).isoformat().replace("+00:00", "Z")
        else:
            created_s = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        out.append(
            DraftRow(
                id=str(r["id"]),
                channel=str(r.get("channel") or ""),
                confidence_tier=str(r.get("confidence_tier") or ""),
                draft=(r.get("draft") if isinstance(r.get("draft"), dict) else {}),
                created_at_utc=created_s,
            )
        )
    return DraftsOut(drafts=out)


class ComplianceEventRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at_utc: str


class ComplianceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[ComplianceEventRow] = Field(default_factory=list)


@router.get("/recalls/{recall_case_id}/compliance", response_model=ComplianceOut)
def recall_compliance(recall_case_id: str, limit: int = 250) -> ComplianceOut:
    repos = _repos()
    rid = _as_uuid(recall_case_id)
    events = repos.recalls.list_compliance_events(recall_case_id=rid, limit=limit)
    out: list[ComplianceEventRow] = []
    for e in events:
        created = e.get("created_at")
        if isinstance(created, datetime):
            created_s = created.astimezone(UTC).isoformat().replace("+00:00", "Z")
        else:
            created_s = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        out.append(
            ComplianceEventRow(
                event_type=str(e.get("event_type") or ""),
                message=str(e.get("message") or ""),
                payload=(e.get("payload") if isinstance(e.get("payload"), dict) else {}),
                created_at_utc=created_s,
            )
        )
    return ComplianceOut(events=out)


class ApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = "manager@example.com"
    action: Literal[
        "approve_confirmed_affected_batch",
        "approve_likely_affected_batch",
        "approve_possible_affected_batch",
        "approve_reassurance_batch",
        "reject_batch",
    ]


class ApprovalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    approvals_count: int


@router.post("/recalls/{recall_case_id}/approvals", response_model=ApprovalOut)
def create_approval(recall_case_id: str, inp: ApprovalIn) -> ApprovalOut:
    repos = _repos()
    rid = _as_uuid(recall_case_id)
    if repos.recalls.get_recall_case(rid) is None:
        raise HTTPException(status_code=404, detail="not found")
    approval_id = repos.recalls.insert_approval(recall_case_id=rid, approved_by=inp.approved_by, action=inp.action)
    repos.recalls.insert_compliance_event(
        recall_case_id=rid,
        event_type="approval",
        message=f"{inp.action} by {inp.approved_by}",
        payload={"action": inp.action, "approved_by": inp.approved_by},
    )
    count = repos.recalls.count_approvals(recall_case_id=rid, action_prefix=inp.action)
    return ApprovalOut(approval_id=str(approval_id), approvals_count=count)
