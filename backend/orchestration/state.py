from __future__ import annotations

import enum
from dataclasses import dataclass


class RecallLifecycleState(str, enum.Enum):
    """
    Phase 9: durable 20-state recall lifecycle.

    Stored in `recall_cases.state` (Postgres enum `recall_case_state`).
    """

    # Ingestion / intake
    signal_detected = "signal_detected"
    created = "created"
    intake_queued = "intake_queued"
    intake_running = "intake_running"
    intake_parsed = "intake_parsed"

    # Human loop: ambiguity / low confidence / low severity / scope disputes
    requires_human_review = "requires_human_review"
    scope_review_pending = "scope_review_pending"
    scope_review_approved = "scope_review_approved"

    # Trace
    trace_queued = "trace_queued"
    trace_running = "trace_running"
    trace_completed = "trace_completed"

    # Match
    match_queued = "match_queued"
    match_running = "match_running"
    match_completed = "match_completed"

    # Ops + Comms (parallel)
    ops_running = "ops_running"
    ops_completed = "ops_completed"
    comms_running = "comms_running"
    comms_completed = "comms_completed"

    # Human loop: manager approves send/quarantine batches
    awaiting_manager_approval = "awaiting_manager_approval"
    closed = "closed"


@dataclass(frozen=True)
class Transition:
    from_state: RecallLifecycleState
    to_state: RecallLifecycleState


# Allowed transitions: deliberately strict to keep the state machine honest.
ALLOWED_TRANSITIONS: set[Transition] = {
    Transition(RecallLifecycleState.signal_detected, RecallLifecycleState.intake_queued),
    Transition(RecallLifecycleState.created, RecallLifecycleState.intake_queued),
    Transition(RecallLifecycleState.intake_queued, RecallLifecycleState.intake_running),
    Transition(RecallLifecycleState.intake_running, RecallLifecycleState.intake_parsed),
    Transition(RecallLifecycleState.intake_running, RecallLifecycleState.requires_human_review),
    Transition(RecallLifecycleState.intake_parsed, RecallLifecycleState.requires_human_review),
    Transition(RecallLifecycleState.intake_parsed, RecallLifecycleState.trace_queued),
    Transition(RecallLifecycleState.intake_parsed, RecallLifecycleState.scope_review_pending),
    Transition(RecallLifecycleState.requires_human_review, RecallLifecycleState.scope_review_pending),
    Transition(RecallLifecycleState.scope_review_pending, RecallLifecycleState.scope_review_approved),
    Transition(RecallLifecycleState.scope_review_approved, RecallLifecycleState.trace_queued),
    Transition(RecallLifecycleState.trace_queued, RecallLifecycleState.trace_running),
    Transition(RecallLifecycleState.trace_running, RecallLifecycleState.trace_completed),
    Transition(RecallLifecycleState.trace_completed, RecallLifecycleState.match_queued),
    # Scope-change rerun: after pausing for manager approval, we may need to re-run Match for delta work.
    Transition(RecallLifecycleState.awaiting_manager_approval, RecallLifecycleState.match_queued),
    Transition(RecallLifecycleState.match_queued, RecallLifecycleState.match_running),
    Transition(RecallLifecycleState.match_running, RecallLifecycleState.match_completed),
    Transition(RecallLifecycleState.match_completed, RecallLifecycleState.ops_running),
    Transition(RecallLifecycleState.match_completed, RecallLifecycleState.comms_running),
    # Parallel branch interleavings (single persisted state field, so allow safe re-ordering).
    Transition(RecallLifecycleState.ops_running, RecallLifecycleState.comms_running),
    Transition(RecallLifecycleState.comms_running, RecallLifecycleState.ops_running),
    Transition(RecallLifecycleState.ops_running, RecallLifecycleState.ops_completed),
    Transition(RecallLifecycleState.comms_running, RecallLifecycleState.comms_completed),
    Transition(RecallLifecycleState.ops_running, RecallLifecycleState.comms_completed),
    Transition(RecallLifecycleState.comms_running, RecallLifecycleState.ops_completed),
    Transition(RecallLifecycleState.ops_completed, RecallLifecycleState.comms_completed),
    Transition(RecallLifecycleState.comms_completed, RecallLifecycleState.ops_completed),
    Transition(RecallLifecycleState.ops_completed, RecallLifecycleState.awaiting_manager_approval),
    Transition(RecallLifecycleState.comms_completed, RecallLifecycleState.awaiting_manager_approval),
    Transition(RecallLifecycleState.awaiting_manager_approval, RecallLifecycleState.closed),
    Transition(RecallLifecycleState.scope_review_pending, RecallLifecycleState.closed),
    Transition(RecallLifecycleState.requires_human_review, RecallLifecycleState.closed),
}


def validate_transition(
    from_state: RecallLifecycleState, to_state: RecallLifecycleState, *, allow_same: bool = True
) -> None:
    if allow_same and from_state == to_state:
        return
    if Transition(from_state, to_state) not in ALLOWED_TRANSITIONS:
        raise ValueError(f"illegal transition: {from_state.value} -> {to_state.value}")
