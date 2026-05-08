from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.agents.intake_agent import HazardType, RecallSpec as IntakeRecallSpec
from pydantic import BaseModel, ConfigDict, Field

from backend.db.models import CustomerProfile, PaymentType, PosTransaction, ScoredTransaction
from backend.db.repositories import RecallRepository
from backend.engine.composition_engine import InventoryCompositionEngine
from backend.engine.confidence import (
    ConfidenceTier,
    actionability_score,
    bump_tier_for_vulnerable_population,
    map_tier,
)
from backend.engine.recall_graph import BlastRadius


def _as_uuid(v: Any) -> uuid.UUID | None:
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except Exception:
        return None


@dataclass(frozen=True)
class MatchAgent:
    """
    Phase 6 Match Agent (mostly deterministic).

    Computes per-transaction affected probability by querying the InventoryCompositionEngine
    and maps to a confidence tier. Optionally persists to scored_transactions.
    """

    session_factory: sessionmaker[Session]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_composition", InventoryCompositionEngine(self.session_factory))
        object.__setattr__(self, "_recalls_repo", RecallRepository(self.session_factory))

    def score_transactions(
        self,
        blast_radius: BlastRadius,
        recall_spec: IntakeRecallSpec,
        *,
        recall_case_id: uuid.UUID | None = None,
        limit: int | None = None,
    ) -> list["ScoredTransactionOut"]:
        tx_ids: list[uuid.UUID] = []
        for w in blast_radius.affected_transactions_window:
            tx_ids.extend(w.transaction_ids)
        if limit is not None:
            tx_ids = tx_ids[:limit]
        if not tx_ids:
            return []

        affected_pallet_ids = {p.pallet_id for p in blast_radius.affected_pallets}
        affected_lot_ids = self._affected_finished_product_lot_ids(affected_pallet_ids)

        rows = self._load_transactions(tx_ids)
        results: list[ScoredTransactionOut] = []
        for tx in rows:
            result = self._score_one_transaction(
                tx=tx,
                recall_spec=recall_spec,
                affected_pallet_ids=affected_pallet_ids,
                affected_lot_ids=affected_lot_ids,
            )
            results.append(result)

        if recall_case_id is not None:
            self._recalls_repo.upsert_scored_transactions(recall_case_id=recall_case_id, scored=results)
        return results

    def _load_transactions(self, tx_ids: list[uuid.UUID]) -> list[PosTransaction]:
        with self.session_factory() as s:
            # Avoid enormous parameter lists from ORM `IN (...)` expansion.
            rows = (
                s.query(PosTransaction)  # type: ignore[attr-defined]
                .from_statement(
                    text("SELECT * FROM pos_transactions WHERE id = ANY(CAST(:ids AS uuid[]))")
                )
                .params(ids=tx_ids)
                .all()
            )
            # Deterministic ordering
            rows.sort(key=lambda t: str(t.id))
            return rows

    def _affected_finished_product_lot_ids(self, affected_pallet_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        if not affected_pallet_ids:
            return set()
        with self.session_factory() as s:
            rows = s.execute(
                text(
                    """
                    SELECT DISTINCT finished_product_lot_id
                    FROM pallets
                    WHERE id = ANY(CAST(:pallet_ids AS uuid[]))
                    """
                ),
                {"pallet_ids": list(affected_pallet_ids)},
            ).scalars().all()
        return {uuid.UUID(str(r)) for r in rows}

    def _customer_profile(self, customer_id: uuid.UUID | None) -> CustomerProfile | None:
        if customer_id is None:
            return None
        with self.session_factory() as s:
            row = s.execute(text("SELECT profile FROM customers WHERE id = :id"), {"id": customer_id}).scalar_one_or_none()
        if not isinstance(row, dict):
            return None
        try:
            return CustomerProfile.model_validate(row)
        except Exception:
            return None

    def _score_one_transaction(
        self,
        *,
        tx: PosTransaction,
        recall_spec: IntakeRecallSpec,
        affected_pallet_ids: set[uuid.UUID],
        affected_lot_ids: set[uuid.UUID],
    ) -> ScoredTransactionOut:
        ts = tx.timestamp.astimezone(UTC)

        # Compute per-line-item affected probability; aggregate by quantity.
        total_qty = 0
        weighted_prob = 0.0
        max_prob = 0.0
        for li in tx.line_items:
            product_id = _as_uuid(li.get("finished_product_id"))
            qty = int(li.get("quantity_units") or 0)
            if product_id is None or qty <= 0:
                continue
            prob = self._affected_probability_for_item(
                store_id=tx.store_id,
                product_id=product_id,
                ts=ts,
                line_item=li,
                affected_pallet_ids=affected_pallet_ids,
                affected_lot_ids=affected_lot_ids,
            )
            total_qty += qty
            weighted_prob += prob * qty
            max_prob = max(max_prob, prob)

        affected_prob = (weighted_prob / total_qty) if total_qty > 0 else max_prob
        # Float safety
        if affected_prob < 0.0:
            affected_prob = 0.0
        if affected_prob > 1.0:
            affected_prob = 1.0

        # Actionability: for now use shelf-life from pallet lots + symptom timeline.
        shelf_days = self._expected_shelf_life_days_remaining(store_id=tx.store_id, ts=ts, affected_pallet_ids=affected_pallet_ids)
        days_since = 0.0  # purchase time is now; later phases can compute relative to recall date.
        act = actionability_score(
            days_since_purchase=float(days_since),
            shelf_life_days_remaining=shelf_days,
            symptom_timeline_days=recall_spec.symptom_timeline_days,
        )

        had_family_purchase = True  # in this Phase 6 scaffold, the transaction itself is the family purchase.
        tier = map_tier(affected_probability=affected_prob, actionability=act, had_family_purchase=had_family_purchase)

        # Lot capture provides deterministic proof:
        # - captured affected lot -> Confirmed Affected (unless payment-type degrades)
        # - captured non-affected lot -> Confirmed Unaffected
        captured_lot_ids = [_as_uuid(li.get("finished_product_lot_id")) for li in tx.line_items]
        captured_lot_ids = [lid for lid in captured_lot_ids if lid is not None]
        captured_affected = any(lid in affected_lot_ids for lid in captured_lot_ids)
        captured_any = bool(captured_lot_ids)
        if captured_affected:
            tier = ConfidenceTier.confirmed_affected
        elif captured_any:
            tier = ConfidenceTier.confirmed_unaffected
        else:
            # Without deterministic lot capture, we do not claim "Confirmed" even if probabilistic p~1.0.
            if tier == ConfidenceTier.confirmed_affected:
                tier = ConfidenceTier.likely_affected

        # Payment-type degrade for unknown buyers.
        if tx.payment_type == PaymentType.cash:
            if tier == ConfidenceTier.confirmed_affected:
                tier = ConfidenceTier.likely_affected

        profile = self._customer_profile(tx.customer_id)
        tier2 = bump_tier_for_vulnerable_population(tier=tier, profile=profile, hazard_type=recall_spec.hazard_type)

        details = {
            "confidence_tier": tier2.value,
            "affected_probability": affected_prob,
            "actionability_score": act,
            "payment_type": tx.payment_type.value if hasattr(tx.payment_type, "value") else str(tx.payment_type),
            "customer_id": str(tx.customer_id) if tx.customer_id else None,
        }
        return ScoredTransactionOut(
            transaction_id=tx.id,
            affected_probability=affected_prob,
            confidence_tier=tier2,
            actionability_score=act,
            payment_type=tx.payment_type,
            customer_id=tx.customer_id,
            details=details,
        )

    def _affected_probability_for_item(
        self,
        *,
        store_id: uuid.UUID,
        product_id: uuid.UUID,
        ts: datetime,
        line_item: dict[str, Any],
        affected_pallet_ids: set[uuid.UUID],
        affected_lot_ids: set[uuid.UUID],
    ) -> float:
        lot_id = _as_uuid(line_item.get("finished_product_lot_id"))
        if lot_id is not None:
            # Lot capture overrides probabilistic inference.
            return 0.999 if lot_id in affected_lot_ids else 0.0

        comp = self._composition.compute_composition(store_id, product_id, ts)
        return float(sum(p for pid, p in comp.items() if pid in affected_pallet_ids))

    def _expected_shelf_life_days_remaining(
        self, *, store_id: uuid.UUID, ts: datetime, affected_pallet_ids: set[uuid.UUID]
    ) -> float | None:
        """
        Best-effort shelf-life estimate from pallets in current composition.

        Uses the (store, product, ts) composition for any affected pallet's product lots.
        If no pallets are present, returns None.
        """
        if not affected_pallet_ids:
            return None
        # Pick any affected pallet to learn the product_id; this is an approximation for Phase 6.
        with self.session_factory() as s:
            row = s.execute(
                text(
                    """
                    SELECT fpl.finished_product_id
                    FROM pallets p
                    JOIN finished_product_lots fpl ON fpl.id = p.finished_product_lot_id
                    WHERE p.id = ANY(CAST(:pallet_ids AS uuid[]))
                    LIMIT 1
                    """
                ),
                {"pallet_ids": list(affected_pallet_ids)},
            ).scalar_one_or_none()
        if row is None:
            return None
        product_id = uuid.UUID(str(row))
        comp = self._composition.compute_composition(store_id, product_id, ts)
        if not comp:
            return None
        pallet_ids = list(comp.keys())
        with self.session_factory() as s:
            rows = s.execute(
                text(
                    """
                    SELECT p.id, fpl.best_by_date
                    FROM pallets p
                    JOIN finished_product_lots fpl ON fpl.id = p.finished_product_lot_id
                    WHERE p.id = ANY(CAST(:pids AS uuid[]))
                    """
                ),
                {"pids": pallet_ids},
            ).all()
        best_by_by_pallet = {uuid.UUID(str(pid)): bb for pid, bb in rows}
        expected = 0.0
        weight_total = 0.0
        for pid, prob in comp.items():
            bb = best_by_by_pallet.get(pid)
            if bb is None:
                continue
            days = max((bb.astimezone(UTC) - ts).total_seconds() / 86400.0, 0.0)
            expected += days * float(prob)
            weight_total += float(prob)
        if weight_total <= 0:
            return None
        return expected / weight_total


class ScoredTransactionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: uuid.UUID
    affected_probability: float = Field(ge=0.0, le=1.0)
    confidence_tier: ConfidenceTier
    actionability_score: float = Field(ge=0.0, le=1.0)
    payment_type: PaymentType
    customer_id: uuid.UUID | None
    details: dict[str, Any] = Field(default_factory=dict)

    def to_row(self, *, recall_case_id: uuid.UUID) -> ScoredTransaction:
        return ScoredTransaction(
            recall_case_id=recall_case_id,
            transaction_id=self.transaction_id,
            affected_probability=int(round(self.affected_probability * 1000)),
            details=self.details,
        )
