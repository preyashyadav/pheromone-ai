from __future__ import annotations

import json
import os
import asyncio
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from langgraph.graph import END
from langgraph.graph.state import CompiledStateGraph, StateGraph
from langgraph.types import Command, interrupt
from langgraph.checkpoint.postgres import PostgresSaver

from backend.agents.comms_agent import CommsAgent
from backend.agents.intake_agent import IntakeAgent, RecallSpec as IntakeRecallSpec, VllmClientConfig
from backend.agents.match_agent import MatchAgent
from backend.agents.ops_agent import OpsAgent
from backend.agents.trace_agent import TraceAgent
from backend.db.repositories import (
    CustomerRepository,
    InventoryRepository,
    RecallRepository,
    Repositories,
    SupplyChainRepository,
    make_session_factory,
)
from backend.engine.recall_graph import BlastRadius
from backend.engine.recall_graph import StoreTransactionWindow
from backend.orchestration.state import RecallLifecycleState, validate_transition
from backend.db.db_url import DEFAULT_DATABASE_URL, get_database_url


class GraphState(TypedDict, total=False):
    recall_case_id: str
    provided_spec: dict[str, Any] | None
    recall_spec: dict[str, Any] | None
    blast_radius: dict[str, Any] | None
    scored_transaction_ids: list[str]
    ops_done: bool
    comms_done: bool
    scope_override_transaction_ids: list[str] | None
    # Human-in-loop values are handled via `interrupt` + `Command(resume=...)`.
    # These keys remain for forward-compat scope simulation.
    manager_decision: str | None  # stored for observability only


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _as_uuid(v: Any) -> uuid.UUID:
    if isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


def _overall_confidence(spec: IntakeRecallSpec) -> float:
    vals = []
    for v in (spec.extraction_confidence or {}).values():
        try:
            vals.append(float(v))
        except Exception:
            continue
    if not vals:
        return 0.0
    return float(min(vals))


def _approx_tokens(obj: Any) -> int:
    """
    Dependency-free token approximation for UI telemetry. Prefer OpenAI-style `usage`
    when available; otherwise fall back to a chars/4 heuristic.
    """
    try:
        s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    except Exception:
        s = str(obj)
    return max(1, int(len(s) / 4))


def _usage_tokens(usage: Any) -> tuple[int | None, int | None]:
    if not isinstance(usage, dict):
        return None, None
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    try:
        pt_i = int(pt) if pt is not None else None
    except Exception:
        pt_i = None
    try:
        ct_i = int(ct) if ct is not None else None
    except Exception:
        ct_i = None
    return pt_i, ct_i


def _log_agent_metrics(
    *,
    deps: OrchestrationDeps,
    recall_case_id: uuid.UUID,
    agent: str,
    state: str,
    started_at_s: float,
    input_obj: Any | None = None,
    output_obj: Any | None = None,
    usage: Any | None = None,
) -> None:
    latency_ms = int(max(0.0, (time.time() - started_at_s) * 1000.0))
    prompt_tokens, completion_tokens = _usage_tokens(usage)
    if prompt_tokens is None and input_obj is not None:
        prompt_tokens = _approx_tokens(input_obj)
    if completion_tokens is None and output_obj is not None:
        completion_tokens = _approx_tokens(output_obj)
    deps.repos.recalls.insert_compliance_event(
        recall_case_id=recall_case_id,
        event_type="agent_metrics",
        message=f"{agent}:{state}",
        payload={
            "agent": agent,
            "state": state,
            "latency_ms": latency_ms,
            "tokens_in": int(prompt_tokens or 0),
            "tokens_out": int(completion_tokens or 0),
            "ts": _now_utc().isoformat().replace("+00:00", "Z"),
        },
    )


class EventBroker:
    """
    In-process pubsub for SSE. Durable state comes from Postgres; this is for live streaming only.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[uuid.UUID, list[queue.Queue[str]]] = {}

    def subscribe(self, recall_case_id: uuid.UUID) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue()
        with self._lock:
            self._subs.setdefault(recall_case_id, []).append(q)
        return q

    def unsubscribe(self, recall_case_id: uuid.UUID, q: queue.Queue[str]) -> None:
        with self._lock:
            arr = self._subs.get(recall_case_id) or []
            self._subs[recall_case_id] = [x for x in arr if x is not q]

    def publish(self, recall_case_id: uuid.UUID, payload: dict[str, Any]) -> None:
        msg = json.dumps(payload, default=str)
        with self._lock:
            subs = list(self._subs.get(recall_case_id) or [])
        for q in subs:
            try:
                q.put_nowait(msg)
            except Exception:
                continue


BROKER = EventBroker()


@dataclass(frozen=True)
class OrchestrationDeps:
    repos: Repositories
    session_factory: sessionmaker[Session]
    intake_agent: IntakeAgent
    trace_agent: TraceAgent
    match_agent: MatchAgent
    ops_agent: OpsAgent
    comms_agent: CommsAgent


def _deps_from_db_url(db_url: str) -> OrchestrationDeps:
    engine = create_engine(db_url, pool_pre_ping=True)
    sf = make_session_factory(engine)
    repos = Repositories(
        supply_chain=SupplyChainRepository(sf),
        inventory=InventoryRepository(sf),
        customers=CustomerRepository(sf),
        recalls=RecallRepository(sf),
    )
    # IntakeAgent supports an injectable httpx client for tests; Phase 9 orchestration
    # primarily uses `provided_spec` and keeps this config as a reasonable default.
    vllm = VllmClientConfig()
    return OrchestrationDeps(
        repos=repos,
        session_factory=sf,
        intake_agent=IntakeAgent(vllm),
        trace_agent=TraceAgent(sf),
        match_agent=MatchAgent(sf),
        ops_agent=OpsAgent(sf),
        comms_agent=CommsAgent(sf),
    )


def _set_case_state(repos: RecallRepository, recall_case_id: uuid.UUID, next_state: RecallLifecycleState) -> None:
    rc = repos.get_recall_case(recall_case_id)
    if rc is None:
        raise KeyError("recall_case not found")
    cur = RecallLifecycleState(str(rc.state.value))
    validate_transition(cur, next_state, allow_same=True)
    repos.update_recall_case_state(recall_case_id, next_state.value)


def _intake_node(state: GraphState, deps: OrchestrationDeps) -> GraphState:
    recall_case_id = _as_uuid(state["recall_case_id"])
    t0 = time.time()
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.intake_running)

    if state.get("provided_spec"):
        provided = cast(dict[str, Any], state["provided_spec"])
        spec = IntakeRecallSpec.model_validate(provided)
    else:
        # In Phase 9 tests we pass a structured spec, but keep a fallback for real usage.
        raw = deps.repos.recalls.get_recall_spec(recall_case_id=recall_case_id) or {}
        spec = deps.intake_agent.parse(raw)

    deps.repos.recalls.upsert_recall_spec(recall_case_id=recall_case_id, spec=spec.model_dump(mode="json"))
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.intake_parsed)
    _log_agent_metrics(
        deps=deps,
        recall_case_id=recall_case_id,
        agent="intake",
        state="completed",
        started_at_s=t0,
        input_obj=(state.get("provided_spec") or {}),
        output_obj=spec.model_dump(mode="json"),
        usage=getattr(deps.intake_agent, "last_llm_usage", None),
    )
    return {"recall_spec": spec.model_dump(mode="json")}


def _route_after_intake(state: GraphState, deps: OrchestrationDeps) -> str:
    recall_case_id = _as_uuid(state["recall_case_id"])
    spec_d = state.get("recall_spec") or deps.repos.recalls.get_recall_spec(recall_case_id=recall_case_id) or {}
    spec = IntakeRecallSpec.model_validate(spec_d)
    conf = _overall_confidence(spec)
    sev = (spec.severity or "").strip().lower()
    if spec.requires_human_review or conf < 0.6 or sev in {"low", "unknown", ""}:
        _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.requires_human_review)
        return "scope_review"
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.trace_queued)
    return "trace"


def _scope_review_node(state: GraphState, deps: OrchestrationDeps) -> GraphState:
    recall_case_id = _as_uuid(state["recall_case_id"])
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.scope_review_pending)
    approved = interrupt({"type": "scope_review_required", "recall_case_id": str(recall_case_id)})
    if bool(approved):
        _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.scope_review_approved)
        _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.trace_queued)
    return {}


def _trace_node(state: GraphState, deps: OrchestrationDeps) -> GraphState:
    recall_case_id = _as_uuid(state["recall_case_id"])
    t0 = time.time()
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.trace_running)

    spec_d = state.get("recall_spec") or deps.repos.recalls.get_recall_spec(recall_case_id=recall_case_id) or {}
    spec = IntakeRecallSpec.model_validate(spec_d)
    blast = deps.trace_agent.build(spec)
    deps.repos.recalls.insert_blast_radius_snapshot(
        recall_case_id=recall_case_id, snapshot=blast.model_dump(mode="json")
    )
    # Persist scope version for scope-delta matching on reruns.
    tx_ids = []
    for w in blast.affected_transactions_window:
        tx_ids.extend([str(t) for t in w.transaction_ids])
    deps.repos.recalls.insert_scope_version(recall_case_id=recall_case_id, scope={"transaction_ids": tx_ids})

    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.trace_completed)
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.match_queued)
    _log_agent_metrics(
        deps=deps,
        recall_case_id=recall_case_id,
        agent="trace",
        state="completed",
        started_at_s=t0,
        input_obj=spec_d,
        output_obj=blast.model_dump(mode="json"),
    )
    return {"blast_radius": blast.model_dump(mode="json")}


def _match_node(state: GraphState, deps: OrchestrationDeps) -> GraphState:
    recall_case_id = _as_uuid(state["recall_case_id"])
    t0 = time.time()
    rc = deps.repos.recalls.get_recall_case(recall_case_id)
    if rc is None:
        raise KeyError("recall_case not found")
    cur = RecallLifecycleState(str(rc.state.value))
    if cur == RecallLifecycleState.match_running:
        # Crash recovery: we may restart while Match was in-flight.
        _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.match_running)
    else:
        if cur != RecallLifecycleState.match_queued:
            _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.match_queued)
        _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.match_running)

    # Phase 9 test hook: simulate a crash mid-Match exactly once per recall case.
    if (os.getenv("PHEROMONE_TEST_CRASH_MATCH_ONCE", "").strip() == "1"):
        rc = deps.repos.recalls.get_recall_case(recall_case_id)
        details = (rc.source_details or {}) if rc is not None else {}
        if not details.get("_crash_match_once_done"):
            details["_crash_match_once_done"] = True
            deps.repos.recalls.set_recall_case_source_details(recall_case_id=recall_case_id, source_details=details)
            raise RuntimeError("simulated crash during match")

    spec_d = state.get("recall_spec") or deps.repos.recalls.get_recall_spec(recall_case_id=recall_case_id) or {}
    spec = IntakeRecallSpec.model_validate(spec_d)
    blast_d = state.get("blast_radius") or deps.repos.recalls.get_latest_blast_radius_snapshot(
        recall_case_id=recall_case_id
    )
    blast = BlastRadius.model_validate(blast_d or {})

    override_ids = state.get("scope_override_transaction_ids") or []
    if override_ids:
        # Scope expansion simulation: score only the delta vs already-scored tx ids.
        already = deps.repos.recalls.get_scored_transaction_ids(recall_case_id=recall_case_id)
        requested = {_as_uuid(t) for t in override_ids}
        delta = sorted(list(requested - already), key=lambda x: str(x))
        if delta:
            sid = blast.affected_stores[0].store_id if blast.affected_stores else uuid.uuid4()
            now = _now_utc()
            blast = blast.model_copy(
                update={
                    "affected_transactions_window": [
                        {"store_id": sid, "start_utc": now, "end_utc": now, "transaction_ids": delta}
                    ]
                }
            )
        else:
            blast = blast.model_copy(update={"affected_transactions_window": []})

    scored = deps.match_agent.score_transactions(blast, spec, recall_case_id=recall_case_id)
    tx_ids_out = [str(s.transaction_id) for s in scored if getattr(s, "transaction_id", None) is not None]
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.match_completed)
    _log_agent_metrics(
        deps=deps,
        recall_case_id=recall_case_id,
        agent="match",
        state="completed",
        started_at_s=t0,
        input_obj={"blast_radius": (blast_d or {}), "override_ids": override_ids},
        output_obj={"scored_count": len(tx_ids_out)},
    )
    return {"scored_transaction_ids": tx_ids_out}


def _ops_node(state: GraphState, deps: OrchestrationDeps) -> GraphState:
    recall_case_id = _as_uuid(state["recall_case_id"])
    if deps.repos.recalls.count_employee_tasks(recall_case_id=recall_case_id) > 0:
        _log_agent_metrics(
            deps=deps,
            recall_case_id=recall_case_id,
            agent="ops",
            state="cached",
            started_at_s=time.time(),
            input_obj={},
            output_obj={"tasks": "already_present"},
            usage=getattr(deps.ops_agent, "last_llm_usage", None),
        )
        return {"ops_done": True}
    t0 = time.time()
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.ops_running)

    blast_d = state.get("blast_radius") or deps.repos.recalls.get_latest_blast_radius_snapshot(
        recall_case_id=recall_case_id
    )
    blast = BlastRadius.model_validate(blast_d or {})
    spec_d = state.get("recall_spec") or deps.repos.recalls.get_recall_spec(recall_case_id=recall_case_id) or {}
    spec = IntakeRecallSpec.model_validate(spec_d)

    # OpsAgent wants per-store calls; use the affected stores list if present.
    for srow in blast.affected_stores:
        sid = getattr(srow, "store_id", None)
        if sid is None:
            continue
        deps.ops_agent.generate_tasks(
            blast_radius=blast,
            scored_transactions=[],
            store_id=_as_uuid(sid),
            recall_case_id=recall_case_id,
            recall_spec=spec,
            now_utc=_now_utc(),
        )

    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.ops_completed)
    _log_agent_metrics(
        deps=deps,
        recall_case_id=recall_case_id,
        agent="ops",
        state="completed",
        started_at_s=t0,
        input_obj={"blast_radius": (blast_d or {}), "affected_stores": [str(x.store_id) for x in blast.affected_stores]},
        output_obj={"tasks_count": deps.repos.recalls.count_employee_tasks(recall_case_id=recall_case_id)},
        usage=getattr(deps.ops_agent, "last_llm_usage", None),
    )
    return {"ops_done": True}


def _comms_node(state: GraphState, deps: OrchestrationDeps) -> GraphState:
    recall_case_id = _as_uuid(state["recall_case_id"])
    if deps.repos.recalls.count_notification_drafts(recall_case_id=recall_case_id) > 0:
        _log_agent_metrics(
            deps=deps,
            recall_case_id=recall_case_id,
            agent="comms",
            state="cached",
            started_at_s=time.time(),
            input_obj={},
            output_obj={"drafts": "already_present"},
            usage=getattr(deps.comms_agent, "last_llm_usage", None),
        )
        return {"comms_done": True}
    t0 = time.time()
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.comms_running)

    spec_d = state.get("recall_spec") or deps.repos.recalls.get_recall_spec(recall_case_id=recall_case_id) or {}
    spec = IntakeRecallSpec.model_validate(spec_d)

    scored_rows = deps.repos.recalls.list_scored_transactions_minimal(recall_case_id=recall_case_id)

    @dataclass(frozen=True)
    class _ScoredLike:
        transaction_id: uuid.UUID
        confidence_tier: str
        details: dict[str, Any]

    scored_like = [
        _ScoredLike(
            transaction_id=r["transaction_id"],
            confidence_tier=str((r.get("details") or {}).get("confidence_tier") or ""),
            details=cast(dict[str, Any], r.get("details") or {}),
        )
        for r in scored_rows
    ]
    deps.comms_agent.draft_notifications(scored_like, spec, recall_case_id=recall_case_id, now_utc=_now_utc())

    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.comms_completed)
    _log_agent_metrics(
        deps=deps,
        recall_case_id=recall_case_id,
        agent="comms",
        state="completed",
        started_at_s=t0,
        input_obj={"scored_count": len(scored_like)},
        output_obj={"drafts_count": deps.repos.recalls.count_notification_drafts(recall_case_id=recall_case_id)},
        usage=getattr(deps.comms_agent, "last_llm_usage", None),
    )
    return {"comms_done": True}


def _manager_approval_node(state: GraphState, deps: OrchestrationDeps) -> GraphState:
    recall_case_id = _as_uuid(state["recall_case_id"])
    t0 = time.time()
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.awaiting_manager_approval)

    # Barrier: only pause when both parallel branches have finished.
    if not (state.get("ops_done") and state.get("comms_done")):
        return {}

    decision = interrupt({"type": "manager_approval_required", "recall_case_id": str(recall_case_id)})
    # Decision captured; close (approve/reject is handled at higher layers in later phases).
    _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.closed)
    _log_agent_metrics(
        deps=deps,
        recall_case_id=recall_case_id,
        agent="manager_approval",
        state="completed",
        started_at_s=t0,
        input_obj={"decision": bool(decision)},
        output_obj={},
    )
    return {"manager_decision": str(decision)}


def build_graph(*, deps: OrchestrationDeps) -> StateGraph:
    g: StateGraph = StateGraph(GraphState)
    g.add_node("intake", lambda s: _intake_node(s, deps))
    g.add_node("scope_review", lambda s: _scope_review_node(s, deps))
    g.add_node("trace", lambda s: _trace_node(s, deps))
    g.add_node("match", lambda s: _match_node(s, deps))
    g.add_node("ops", lambda s: _ops_node(s, deps))
    g.add_node("comms", lambda s: _comms_node(s, deps))
    g.add_node("manager_approval", lambda s: _manager_approval_node(s, deps))

    g.set_entry_point("intake")
    g.add_conditional_edges("intake", lambda s: _route_after_intake(s, deps), {"scope_review": "scope_review", "trace": "trace"})
    g.add_edge("scope_review", "trace")
    g.add_edge("trace", "match")

    # Parallel fan-out (Ops + Comms), then join at manager approval.
    g.add_edge("match", "ops")
    g.add_edge("match", "comms")
    g.add_edge("ops", "manager_approval")
    g.add_edge("comms", "manager_approval")
    g.add_edge("manager_approval", END)
    return g


def _db_url() -> str:
    db_url = get_database_url()
    if db_url == DEFAULT_DATABASE_URL and not (os.environ.get("DATABASE_URL") or "").strip():
        print(f"[db] No DATABASE_URL set; using default {DEFAULT_DATABASE_URL}")
    return db_url


def _checkpointer_conninfo(db_url: str) -> str:
    # LangGraph PostgresSaver expects a libpq conninfo / DSN, not a SQLAlchemy driver URL.
    return db_url.replace("postgresql+psycopg://", "postgresql://")


def _run_graph_with_streaming(
    *, graph: CompiledStateGraph, recall_case_id: uuid.UUID, config: dict[str, Any], input_state: Any | None
) -> None:
    for update in graph.stream(input_state, config=config, stream_mode="updates"):  # type: ignore[arg-type]
        # `update` is a dict like {"node_name": {"state_key": value, ...}}
        for node_name in update.keys():
            BROKER.publish(
                recall_case_id,
                {
                    "ts": _now_utc().isoformat().replace("+00:00", "Z"),
                    "event": "node_transition",
                    "node": str(node_name),
                },
            )


def start_or_resume_recall(
    *, recall_case_id: uuid.UUID, provided_spec: dict[str, Any] | None, scope_override_transaction_ids: list[str] | None
) -> None:
    """
    Fire-and-forget orchestration runner. Durable state is in Postgres:
    - `recall_cases.state` (our lifecycle labels)
    - LangGraph checkpoints (thread_id == recall_case_id)
    """
    deps = _deps_from_db_url(_db_url())
    rc = deps.repos.recalls.get_recall_case(recall_case_id)
    if rc is None:
        raise KeyError("recall_case not found")
    cur = RecallLifecycleState(str(rc.state.value))
    if cur in {RecallLifecycleState.signal_detected, RecallLifecycleState.created}:
        _set_case_state(deps.repos.recalls, recall_case_id, RecallLifecycleState.intake_queued)

    graph_def = build_graph(deps=deps)
    with PostgresSaver.from_conn_string(_checkpointer_conninfo(_db_url())) as checkpointer:
        checkpointer.setup()
        graph = graph_def.compile(checkpointer=checkpointer)

        input_state: GraphState | None
        if cur in {RecallLifecycleState.signal_detected, RecallLifecycleState.created, RecallLifecycleState.intake_queued}:
            input_state = {
                "recall_case_id": str(recall_case_id),
                "provided_spec": provided_spec,
                "scope_override_transaction_ids": scope_override_transaction_ids,
            }
        else:
            # Resume from persisted checkpoint without re-running entry nodes.
            input_state = None
        try:
            config = {"configurable": {"thread_id": str(recall_case_id)}}
            _run_graph_with_streaming(
                graph=graph, recall_case_id=recall_case_id, config=config, input_state=input_state
            )
        except Exception as e:
            BROKER.publish(recall_case_id, {"ts": _now_utc().isoformat().replace("+00:00", "Z"), "event": "error", "error": str(e)})
            return


def update_and_resume(
    *, recall_case_id: uuid.UUID, updates: dict[str, Any], as_node: str | None = None
) -> None:
    deps = _deps_from_db_url(_db_url())
    graph_def = build_graph(deps=deps)
    with PostgresSaver.from_conn_string(_checkpointer_conninfo(_db_url())) as checkpointer:
        checkpointer.setup()
        graph = graph_def.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": str(recall_case_id)}}
        new_config = graph.update_state(config, updates, as_node=as_node)
        try:
            _run_graph_with_streaming(
                graph=graph,
                recall_case_id=recall_case_id,
                config=cast(dict[str, Any], new_config or config),
                input_state={},
            )
        except Exception as e:
            BROKER.publish(recall_case_id, {"ts": _now_utc().isoformat().replace("+00:00", "Z"), "event": "error", "error": str(e)})
            return


def resume_from_interrupt(*, recall_case_id: uuid.UUID, resume_value: Any) -> None:
    deps = _deps_from_db_url(_db_url())
    graph_def = build_graph(deps=deps)
    with PostgresSaver.from_conn_string(_checkpointer_conninfo(_db_url())) as checkpointer:
        checkpointer.setup()
        graph = graph_def.compile(checkpointer=checkpointer)
        try:
            _run_graph_with_streaming(
                graph=graph,
                recall_case_id=recall_case_id,
                config={"configurable": {"thread_id": str(recall_case_id)}},
                input_state=Command(resume=resume_value),
            )
        except Exception as e:
            BROKER.publish(recall_case_id, {"ts": _now_utc().isoformat().replace("+00:00", "Z"), "event": "error", "error": str(e)})
            return


def score_scope_delta(*, recall_case_id: uuid.UUID, transaction_ids: list[str]) -> int:
    """
    Phase 9 scope-change hook: score only newly-added transactions without re-running Intake/Trace.

    Returns number of newly-scored transactions inserted.
    """
    try:
        deps = _deps_from_db_url(_db_url())
        spec_d = deps.repos.recalls.get_recall_spec(recall_case_id=recall_case_id) or {}
        spec = IntakeRecallSpec.model_validate(spec_d)
        blast_d = deps.repos.recalls.get_latest_blast_radius_snapshot(recall_case_id=recall_case_id) or {}
        blast = BlastRadius.model_validate(blast_d)

        already = deps.repos.recalls.get_scored_transaction_ids(recall_case_id=recall_case_id)
        requested = [_as_uuid(t) for t in transaction_ids]
        delta = [t for t in requested if t not in already]
        if not delta:
            return 0

        sid = blast.affected_stores[0].store_id if blast.affected_stores else uuid.uuid4()
        now = _now_utc()
        scoped = BlastRadius(
            affected_pallets=blast.affected_pallets,
            affected_stores=blast.affected_stores,
            affected_transactions_window=[
                StoreTransactionWindow(store_id=sid, start_utc=now, end_utc=now, transaction_ids=delta)
            ],
            affected_finished_product_ids=blast.affected_finished_product_ids,
            inferred_facility_ids=blast.inferred_facility_ids,
        )
        scored = deps.match_agent.score_transactions(scoped, spec, recall_case_id=recall_case_id)
        return len(scored)
    except Exception as e:
        BROKER.publish(
            recall_case_id,
            {"ts": _now_utc().isoformat().replace("+00:00", "Z"), "event": "error", "error": str(e)},
        )
        return 0


async def sse_events(recall_case_id: uuid.UUID, *, keepalive_s: float = 15.0) -> Any:
    q = BROKER.subscribe(recall_case_id)
    try:
        yield b"event: ping\ndata: {}\n\n"
        last = time.time()
        while True:
            try:
                msg = await asyncio.to_thread(q.get, True, 0.25)
                yield f"data: {msg}\n\n".encode("utf-8")
                last = time.time()
            except queue.Empty:
                if time.time() - last > keepalive_s:
                    yield b"event: ping\ndata: {}\n\n"
                    last = time.time()
    finally:
        BROKER.unsubscribe(recall_case_id, q)
