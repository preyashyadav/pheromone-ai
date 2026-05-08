from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.agents.intake_agent import RecallSpec as IntakeRecallSpec
from backend.agents.intake_agent import VllmClientConfig
from backend.engine.recall_graph import BlastRadius, BlastRadiusBuilder


_PLANT_PREFIX_RE = re.compile(r"\b([A-Z]\d{1,3})-\d{6}-[A-Z]\b")


@dataclass(frozen=True)
class TraceAgent:
    """
    Phase 5 Trace Agent.

    Deterministic by default; uses Qwen3-32B sparingly only for ambiguous inference (disabled on mock vLLM).
    """

    session_factory: sessionmaker[Session]
    vllm_config: VllmClientConfig | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "_builder", BlastRadiusBuilder(self.session_factory))
        if self.vllm_config is None:
            object.__setattr__(self, "_client", None)
            return
        object.__setattr__(
            self,
            "_client",
            httpx.Client(base_url=self.vllm_config.base_url, timeout=self.vllm_config.timeout_s),
        )

    def build(
        self,
        recall_spec: IntakeRecallSpec,
        *,
        store_id: uuid.UUID | None = None,
        time_window: dict[str, Any] | None = None,
        related_notices: Iterable[Any] | None = None,
    ) -> BlastRadius:
        # 1) Deterministic resolution: ingredient lot -> finished product lot -> facility window -> store-scoped.
        ingredient_lot_id = self._resolve_ingredient_lot_id(recall_spec)
        inferred_facility_id, inferred_conf = self._infer_facility_from_lot_code(recall_spec)

        if ingredient_lot_id:
            blast = self._builder.build(ingredient_lot_id=ingredient_lot_id)
        else:
            fpl_id = self._resolve_finished_product_lot_id(recall_spec)
            if fpl_id:
                blast = self._builder.build(finished_product_lot_id=fpl_id)
            else:
                if inferred_facility_id and time_window:
                    ws, we = self._parse_window(time_window)
                    blast = self._builder.build(
                        facility_id=inferred_facility_id, window_start=ws, window_end=we
                    )
                elif store_id and time_window:
                    ws, we = self._parse_window(time_window)
                    with self.session_factory() as s:
                        tx_ids = list(
                            s.execute(
                                text(
                                    "SELECT id FROM pos_transactions WHERE store_id = :sid AND timestamp >= :st AND timestamp <= :en"
                                ),
                                {"sid": store_id, "st": ws, "en": we},
                            ).scalars().all()
                        )
                    blast = BlastRadius(
                        affected_pallets=[],
                        affected_stores=[{"store_id": store_id, "affected_stock_fraction_peak": 1.0}],
                        affected_transactions_window=[
                            {"store_id": store_id, "start_utc": ws, "end_utc": we, "transaction_ids": tx_ids}
                        ],
                        affected_finished_product_ids=[],
                        inferred_facility_ids={},
                    )
                else:
                    blast = BlastRadius()

        if inferred_facility_id and not blast.inferred_facility_ids:
            blast = blast.model_copy(update={"inferred_facility_ids": {str(inferred_facility_id): inferred_conf}})

        # 2) Optional: hierarchical propagation via ingredient parent (blend) if we can identify it.
        blast = self._propagate_hierarchical_if_needed(recall_spec, blast, ingredient_lot_id)

        # 3) Optional multi-source verification could boost certainty later; placeholder hook.
        if related_notices:
            blast = blast

        return blast

    def _parse_window(self, window: dict[str, Any]) -> tuple[datetime, datetime]:
        start_s = str(window.get("start") or "")
        end_s = str(window.get("end") or "")
        start = datetime.fromisoformat(start_s.replace("Z", "+00:00")).astimezone(UTC)
        end = datetime.fromisoformat(end_s.replace("Z", "+00:00")).astimezone(UTC)
        return start, end

    def _resolve_ingredient_lot_id(self, recall_spec: IntakeRecallSpec) -> uuid.UUID | None:
        codes = [lc.value for lc in recall_spec.lot_codes if lc.value]
        if not codes:
            return None
        with self.session_factory() as s:
            for code in codes:
                row = s.execute(
                    text("SELECT id FROM ingredient_lots WHERE lot_code = :c LIMIT 1"), {"c": code}
                ).scalar_one_or_none()
                if row is not None:
                    return uuid.UUID(str(row))
        return None

    def _resolve_finished_product_lot_id(self, recall_spec: IntakeRecallSpec) -> uuid.UUID | None:
        codes = [lc.value for lc in recall_spec.lot_codes if lc.value]
        if not codes:
            return None
        with self.session_factory() as s:
            for code in codes:
                row = s.execute(
                    text("SELECT id FROM finished_product_lots WHERE lot_code = :c LIMIT 1"), {"c": code}
                ).scalar_one_or_none()
                if row is not None:
                    return uuid.UUID(str(row))
        return None

    def _infer_facility_from_lot_code(self, recall_spec: IntakeRecallSpec) -> tuple[uuid.UUID | None, float]:
        for lc in recall_spec.lot_codes:
            m = _PLANT_PREFIX_RE.search(lc.value or "")
            if not m:
                continue
            plant_code = m.group(1)
            with self.session_factory() as s:
                row = s.execute(
                    text("SELECT id FROM facilities WHERE plant_code = :p LIMIT 1"), {"p": plant_code}
                ).scalar_one_or_none()
                if row is not None:
                    return uuid.UUID(str(row)), 0.8
        return None, 0.0

    def _propagate_hierarchical_if_needed(
        self, recall_spec: IntakeRecallSpec, blast: BlastRadius, ingredient_lot_id: uuid.UUID | None
    ) -> BlastRadius:
        if not ingredient_lot_id:
            return blast
        with self.session_factory() as s:
            ing = s.execute(
                text("SELECT ingredient_id FROM ingredient_lots WHERE id = :id"), {"id": ingredient_lot_id}
            ).scalar_one_or_none()
            if ing is None:
                return blast
            parent_id = s.execute(
                text("SELECT parent_ingredient_id FROM ingredients WHERE id = :id"), {"id": ing}
            ).scalar_one_or_none()
            if parent_id is None:
                return blast
            # Any finished products that list the parent ingredient are potentially impacted.
            rows = s.execute(
                text(
                    """
                    SELECT DISTINCT fp.id
                    FROM finished_products fp,
                         LATERAL jsonb_array_elements(fp.ingredient_recipe) ing
                    WHERE (ing->>'ingredient_id')::uuid = :pid
                    """
                ),
                {"pid": parent_id},
            ).scalars().all()
        if not rows:
            return blast
        merged = list({*blast.affected_finished_product_ids, *[uuid.UUID(str(r)) for r in rows]})
        return blast.model_copy(update={"affected_finished_product_ids": merged})
