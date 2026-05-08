from __future__ import annotations

import enum
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.agents.intake_agent import RecallSpec as IntakeRecallSpec, VllmClientConfig
from backend.db.models import EmployeeTask as EmployeeTaskRow
from backend.db.repositories import RecallRepository
from backend.engine.recall_graph import BlastRadius


class TaskType(str, enum.Enum):
    shelf_pull = "shelf_pull"
    backroom_check = "backroom_check"
    pos_block_verify = "pos_block_verify"
    package_scan = "package_scan"
    disposal_quarantine = "disposal_quarantine"
    manager_review = "manager_review"
    photo_evidence = "photo_evidence"


class EmployeeTaskOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: TaskType
    priority: int = Field(ge=1, le=100)
    store_id: uuid.UUID
    description: str
    aisle: str
    shelf: str
    escalation_level: int = Field(ge=0, le=3, default=0)

    def to_row(self, *, recall_case_id: uuid.UUID) -> EmployeeTaskRow:
        return EmployeeTaskRow(
            recall_case_id=recall_case_id,
            task_type=self.task_type.value,
            payload={
                "store_id": str(self.store_id),
                "priority": self.priority,
                "description": self.description,
                "aisle": self.aisle,
                "shelf": self.shelf,
                "escalation_level": self.escalation_level,
            },
            status="open",
        )


class _LlmTasksOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[EmployeeTaskOut] = Field(default_factory=list)


def _stable_location_for_product(*, upc: str | None, product_id: uuid.UUID) -> tuple[str, str]:
    """
    Deterministic aisle/shelf placeholder until we have planogram data.
    """
    key = upc or str(product_id).replace("-", "")
    n = sum(ord(c) for c in key) % 50
    aisle = f"Aisle {1 + (n % 18)}"
    shelf = f"Shelf {1 + (n % 6)}"
    return aisle, shelf


def _escalation_level(*, created_at: datetime, status: str, now: datetime) -> int:
    if status != "open":
        return 0
    age = now - created_at
    if age >= timedelta(hours=2):
        return 2
    if age >= timedelta(minutes=30):
        return 1
    return 0


@dataclass(frozen=True)
class OpsAgent:
    """
    Phase 7: Ops Agent.

    Deterministic structure + optional vLLM text enrichment.
    """

    session_factory: sessionmaker[Session]
    vllm_config: VllmClientConfig | None = None
    http_client: httpx.Client | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "_recalls_repo", RecallRepository(self.session_factory))
        if self.vllm_config is not None:
            client = self.http_client or httpx.Client(
                timeout=self.vllm_config.timeout_s, base_url=self.vllm_config.base_url
            )
            object.__setattr__(self, "_client", client)
        else:
            object.__setattr__(self, "_client", None)

    def generate_tasks(
        self,
        blast_radius: BlastRadius,
        scored_transactions: Iterable[Any],
        store_id: uuid.UUID,
        *,
        recall_case_id: uuid.UUID | None = None,
        recall_spec: IntakeRecallSpec | None = None,
        now_utc: datetime | None = None,
    ) -> list[EmployeeTaskOut]:
        now = (now_utc or datetime.now(tz=UTC)).astimezone(UTC)

        # Determine affected products for this store.
        affected_product_ids = list(blast_radius.affected_finished_product_ids)
        if not affected_product_ids:
            # Fallback: infer from scored transactions' line items when store-scoped triggers don't carry pallets.
            affected_product_ids = self._infer_products_from_scored(scored_transactions, store_id=store_id)

        product_rows = self._load_products(affected_product_ids)
        # Build a deterministic draft task set first.
        draft = self._draft_tasks(
            store_id=store_id,
            products=product_rows,
            blast_radius=blast_radius,
            recall_spec=recall_spec,
        )

        # Optional: let the model rewrite descriptions, but keep structure fixed.
        llm_tasks = self._try_llm_polish(draft, recall_spec=recall_spec)
        tasks = llm_tasks or draft

        # Escalation: if there are existing tasks, compute escalation level based on created_at.
        if recall_case_id is not None:
            existing = self._load_existing_tasks(recall_case_id=recall_case_id, store_id=store_id)
            if existing:
                tasks = self._apply_escalation(tasks, existing=existing, now=now)
            self._upsert_employee_tasks(recall_case_id=recall_case_id, tasks=tasks)

            # POS blocks: one per affected UPC (lot constraint optional).
            self._emit_pos_blocks(recall_case_id=recall_case_id, store_id=store_id, products=product_rows, recall_spec=recall_spec)

        # Stable ordering: priority then type then description.
        tasks.sort(key=lambda t: (t.priority, t.task_type.value, t.description))
        return tasks

    @staticmethod
    def grade_specificity(description: str) -> int:
        """
        Phase 7 test harness uses this as a stand-in for the separate LLM grader.
        Deterministic heuristic: require product + aisle + shelf mentions for a 5.
        """
        d = (description or "").lower()
        score = 1
        if "aisle" in d:
            score += 1
        if "shelf" in d:
            score += 1
        if any(k in d for k in ("upc", "lot", "product", "sku")):
            score += 1
        if any(k in d for k in ("dispose", "quarantine", "pull", "scan", "verify")):
            score += 1
        return max(1, min(5, score))

    def _infer_products_from_scored(self, scored_transactions: Iterable[Any], *, store_id: uuid.UUID) -> list[uuid.UUID]:
        # ScoredTransactionOut details includes transaction_id; load those transactions and extract line_items.
        tx_ids: list[uuid.UUID] = []
        for s in scored_transactions:
            tid = getattr(s, "transaction_id", None)
            if isinstance(tid, uuid.UUID):
                tx_ids.append(tid)
        if not tx_ids:
            return []

        with self.session_factory() as db:
            rows = db.execute(
                text("SELECT line_items FROM pos_transactions WHERE id = ANY(CAST(:ids AS uuid[])) AND store_id = :sid"),
                {"ids": tx_ids, "sid": store_id},
            ).scalars().all()
        out: list[uuid.UUID] = []
        for li_list in rows:
            if not isinstance(li_list, list):
                continue
            for li in li_list:
                if not isinstance(li, dict):
                    continue
                pid = li.get("finished_product_id")
                try:
                    out.append(uuid.UUID(str(pid)))
                except Exception:
                    continue
        # De-dupe deterministic.
        seen: set[uuid.UUID] = set()
        uniq: list[uuid.UUID] = []
        for pid in out:
            if pid in seen:
                continue
            seen.add(pid)
            uniq.append(pid)
        return uniq[:50]

    def _load_products(self, product_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        if not product_ids:
            return []
        with self.session_factory() as db:
            rows = db.execute(
                text("SELECT id, name, upc FROM finished_products WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": product_ids},
            ).all()
        out: list[dict[str, Any]] = []
        for pid, name, upc in rows:
            out.append({"id": uuid.UUID(str(pid)), "name": str(name), "upc": str(upc) if upc else None})
        out.sort(key=lambda r: str(r["id"]))
        return out

    def _draft_tasks(
        self,
        *,
        store_id: uuid.UUID,
        products: list[dict[str, Any]],
        blast_radius: BlastRadius,
        recall_spec: IntakeRecallSpec | None,
    ) -> list[EmployeeTaskOut]:
        tasks: list[EmployeeTaskOut] = []

        # Always include manager review at the top.
        tasks.append(
            EmployeeTaskOut(
                task_type=TaskType.manager_review,
                priority=1,
                store_id=store_id,
                description="Manager review: confirm scope, assign floor lead, and start compliance clock.",
                aisle="Office",
                shelf="N/A",
            )
        )

        # Refrigeration-trigger hint: mention deli zone if present.
        if recall_spec is not None and recall_spec.source_type == "retailer_internal":
            zone_name = self._best_refrigeration_zone_name(store_id)
            if zone_name:
                tasks.append(
                    EmployeeTaskOut(
                        task_type=TaskType.backroom_check,
                        priority=2,
                        store_id=store_id,
                        description=f"Backroom check: inspect deli refrigeration zone '{zone_name}' for temp excursion evidence; quarantine any suspect items.",
                        aisle="Deli",
                        shelf="Cold case",
                    )
                )

        # Create product-scoped tasks.
        top = products[:5]
        prio = 3
        for p in top:
            aisle, shelf = _stable_location_for_product(upc=p.get("upc"), product_id=p["id"])
            pname = p["name"]
            upc = p.get("upc")
            tasks.append(
                EmployeeTaskOut(
                    task_type=TaskType.shelf_pull,
                    priority=prio,
                    store_id=store_id,
                    description=f"Shelf pull: remove '{pname}' (UPC {upc}) from {aisle}, {shelf}. Place into quarantine bin.",
                    aisle=aisle,
                    shelf=shelf,
                )
            )
            prio += 1
            tasks.append(
                EmployeeTaskOut(
                    task_type=TaskType.package_scan,
                    priority=prio,
                    store_id=store_id,
                    description=f"Package scan: scan '{pname}' on {aisle}, {shelf}; photograph lot/date code and attach to case notes.",
                    aisle=aisle,
                    shelf=shelf,
                )
            )
            prio += 1

        # Disposal/quarantine tasks: for store4-fridge we want per-product quarantine tasks.
        if recall_spec is not None and recall_spec.source_type == "retailer_internal" and products:
            for p in products[:20]:
                aisle, shelf = _stable_location_for_product(upc=p.get("upc"), product_id=p["id"])
                tasks.append(
                    EmployeeTaskOut(
                        task_type=TaskType.disposal_quarantine,
                        priority=prio,
                        store_id=store_id,
                        description=f"Disposal/quarantine: move '{p['name']}' (UPC {p.get('upc')}) from {aisle}, {shelf} into refrigeration quarantine until manager sign-off.",
                        aisle=aisle,
                        shelf=shelf,
                    )
                )
                prio += 1
        else:
            tasks.append(
                EmployeeTaskOut(
                    task_type=TaskType.disposal_quarantine,
                    priority=prio,
                    store_id=store_id,
                    description="Disposal/quarantine: stage all pulled items in sealed bin, label with recall id, and hold for manager disposal approval.",
                    aisle="Backroom",
                    shelf="Quarantine bin",
                )
            )
            prio += 1

        tasks.append(
            EmployeeTaskOut(
                task_type=TaskType.pos_block_verify,
                priority=prio,
                store_id=store_id,
                description="POS block verify: confirm affected UPC(s) are blocked at checkout; run a test scan and record result.",
                aisle="Front end",
                shelf="POS 1",
            )
        )
        prio += 1

        tasks.append(
            EmployeeTaskOut(
                task_type=TaskType.photo_evidence,
                priority=prio,
                store_id=store_id,
                description="Photo evidence: take photos of quarantine bin labels + one example package lot/date code; attach to compliance log.",
                aisle="Backroom",
                shelf="Quarantine bin",
            )
        )

        # Keep task list bounded (except internal refrigeration triggers where we need per-product quarantine tasks).
        if recall_spec is not None and recall_spec.source_type == "retailer_internal":
            return tasks[:30]
        return tasks[:15]

    def _best_refrigeration_zone_name(self, store_id: uuid.UUID) -> str | None:
        with self.session_factory() as db:
            return db.execute(
                text("SELECT name FROM refrigeration_zones WHERE store_id = :sid ORDER BY name LIMIT 1"),
                {"sid": store_id},
            ).scalar_one_or_none()

    def _try_llm_polish(
        self, tasks: list[EmployeeTaskOut], *, recall_spec: IntakeRecallSpec | None
    ) -> list[EmployeeTaskOut] | None:
        if self._client is None or self.vllm_config is None:
            return None
        # Keep deterministic structure; ask model only to improve descriptions.
        schema = _LlmTasksOut.model_json_schema()
        system = (
            "You are OpsAgent. Rewrite task descriptions to be specific and actionable.\n"
            "Rules:\n"
            "- Keep task_type, priority, store_id, aisle, shelf unchanged.\n"
            "- Mention product name and UPC when available.\n"
            "- Do not include PII.\n"
        )
        user = {
            "recall_id": getattr(recall_spec, "recall_id", None),
            "tasks": [t.model_dump() for t in tasks],
        }
        payload: dict[str, Any] = {
            "model": self.vllm_config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user)}],
            "temperature": 0.1,
            "max_tokens": 1000,
            "response_format": {"type": "json_schema", "json_schema": {"name": "OpsTasks", "schema": schema}},
        }
        headers: dict[str, str] = {}
        if self.vllm_config.api_key:
            headers["Authorization"] = f"Bearer {self.vllm_config.api_key}"
        try:
            resp = self._client.post("/v1/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if not isinstance(content, str):
                return None
            obj = json.loads(content)
            out = _LlmTasksOut.model_validate(obj)
            return out.tasks
        except Exception:
            return None

    def _load_existing_tasks(self, *, recall_case_id: uuid.UUID, store_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, task_type, payload, status, created_at
                    FROM employee_tasks
                    WHERE recall_case_id = :rc
                      AND (payload->>'store_id')::uuid = :sid
                    ORDER BY created_at ASC
                    """
                ),
                {"rc": recall_case_id, "sid": store_id},
            ).all()
        out: list[dict[str, Any]] = []
        for _, task_type, payload, status, created_at in rows:
            out.append(
                {
                    "task_type": str(task_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "status": str(status),
                    "created_at": created_at,
                }
            )
        return out

    def _apply_escalation(
        self, tasks: list[EmployeeTaskOut], *, existing: list[dict[str, Any]], now: datetime
    ) -> list[EmployeeTaskOut]:
        # Map (task_type, aisle, shelf) -> escalation level from the oldest matching open task.
        idx: dict[tuple[str, str, str], int] = {}
        store_max = 0
        for r in existing:
            payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
            aisle = str(payload.get("aisle") or "")
            shelf = str(payload.get("shelf") or "")
            key = (str(r.get("task_type") or ""), aisle, shelf)
            created_at = r.get("created_at")
            if not isinstance(created_at, datetime):
                continue
            lvl = _escalation_level(created_at=created_at.astimezone(UTC), status=str(r.get("status") or ""), now=now)
            idx[key] = max(idx.get(key, 0), lvl)
            store_max = max(store_max, lvl)

        updated: list[EmployeeTaskOut] = []
        for t in tasks:
            key = (t.task_type.value, t.aisle, t.shelf)
            updated.append(t.model_copy(update={"escalation_level": max(idx.get(key, 0), store_max)}))
        return updated

    def _upsert_employee_tasks(self, *, recall_case_id: uuid.UUID, tasks: list[EmployeeTaskOut]) -> None:
        # Insert as new rows; Phase 9 will handle idempotent graph steps + dedupe keys.
        with self.session_factory() as db:
            for t in tasks:
                db.add(t.to_row(recall_case_id=recall_case_id))
            db.commit()

    def _emit_pos_blocks(
        self,
        *,
        recall_case_id: uuid.UUID,
        store_id: uuid.UUID,
        products: list[dict[str, Any]],
        recall_spec: IntakeRecallSpec | None,
    ) -> None:
        # Use lot codes as lot constraint when present; otherwise allow blocking UPC without lot filter.
        lot_constraint = None
        if recall_spec is not None and getattr(recall_spec, "lot_codes", None):
            lot_constraint = ",".join([lc.value for lc in recall_spec.lot_codes[:10]])

        active_until = datetime.now(tz=UTC) + timedelta(days=30)
        for p in products[:10]:
            upc = p.get("upc")
            if not upc:
                continue
            self._recalls_repo.create_pos_block(
                store_id=store_id,
                upc=str(upc),
                lot_constraint=lot_constraint,
                active_until=active_until,
            )
