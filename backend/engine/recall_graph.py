from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.engine.composition_engine import InventoryCompositionEngine


class AffectedPallet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pallet_id: uuid.UUID
    certainty: float = Field(ge=0.0, le=1.0)


class AffectedStore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: uuid.UUID
    affected_stock_fraction_peak: float = Field(ge=0.0, le=1.0)


class StoreTransactionWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: uuid.UUID
    start_utc: datetime
    end_utc: datetime
    transaction_ids: list[uuid.UUID] = Field(default_factory=list)


class BlastRadius(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affected_pallets: list[AffectedPallet] = Field(default_factory=list)
    affected_stores: list[AffectedStore] = Field(default_factory=list)
    affected_transactions_window: list[StoreTransactionWindow] = Field(default_factory=list)

    # Helpful for later phases/demos (not strictly required, but stable to keep).
    affected_finished_product_ids: list[uuid.UUID] = Field(default_factory=list)
    inferred_facility_ids: dict[str, float] = Field(default_factory=dict)  # facility_id -> confidence


@dataclass(frozen=True)
class BlastRadiusBuilder:
    session_factory: sessionmaker[Session]

    def _compute_peak_affected_fraction(
        self,
        *,
        comp: InventoryCompositionEngine,
        store_id: uuid.UUID,
        product_ids: list[uuid.UUID],
        affected_pallet_ids: set[uuid.UUID],
        candidate_times: list[datetime],
    ) -> float:
        """
        Peak affected fraction for a store over a set of candidate timestamps.

        Deterministic: purely DB + math. We approximate peak over the operational window
        by evaluating composition at transaction timestamps (or shipment timestamps if needed).
        """
        if not candidate_times:
            return 0.0

        peak = 0.0
        for ts in candidate_times:
            for product_id in product_ids:
                composition = comp.compute_composition(store_id, product_id, ts)
                affected = sum(p for pid, p in composition.items() if pid in affected_pallet_ids)
                peak = max(peak, float(affected))
                if peak >= 0.999999:
                    return 1.0
        return min(max(peak, 0.0), 1.0)

    def build(
        self,
        *,
        ingredient_lot_id: uuid.UUID | None = None,
        finished_product_lot_id: uuid.UUID | None = None,
        facility_id: uuid.UUID | None = None,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> BlastRadius:
        if ingredient_lot_id:
            return self._build_from_ingredient_lot(ingredient_lot_id)
        if finished_product_lot_id:
            return self._build_from_finished_product_lot(finished_product_lot_id)
        if facility_id and window_start and window_end:
            return self._build_from_facility_window(facility_id, window_start, window_end)
        return BlastRadius()

    def _build_from_ingredient_lot(self, ingredient_lot_id: uuid.UUID) -> BlastRadius:
        comp = InventoryCompositionEngine(self.session_factory)
        with self.session_factory() as s:
            # Determine per-store operational window for impacted pallets, then pull all transactions
            # in that window. This intentionally does NOT require that a transaction occur after
            # *each* shipment row (which can inadvertently exclude valid purchases in seeded data).
            tx_rows = s.execute(
                text(
                    """
                    WITH pr AS (
                      SELECT pr.id AS production_run_id
                      FROM production_runs pr
                      WHERE EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(pr.ingredient_lots_used) AS elem
                        WHERE (elem->>'ingredient_lot_id')::uuid = :ingredient_lot_id
                      )
                    ),
                    fpl AS (
                      SELECT fpl.id AS finished_product_lot_id, fpl.finished_product_id
                      FROM finished_product_lots fpl
                      JOIN pr ON pr.production_run_id = fpl.production_run_id
                    ),
                    pal AS (
                      SELECT p.id AS pallet_id, p.store_shipment_id, fpl.finished_product_id
                      FROM pallets p
                      JOIN fpl ON fpl.finished_product_lot_id = p.finished_product_lot_id
                    ),
                    ss AS (
                      SELECT ss.store_id,
                             MIN(ss.shipped_at) AS window_start,
                             MAX(COALESCE(ss.arrived_at, ss.shipped_at) + interval '30 days') AS window_end
                      FROM store_shipments ss
                      JOIN pal ON pal.store_shipment_id = ss.id
                      GROUP BY ss.store_id
                    )
                    SELECT t.id AS transaction_id, t.store_id, t.timestamp
                    FROM pos_transactions t
                    JOIN ss ON ss.store_id = t.store_id
                    WHERE t.timestamp >= ss.window_start
                      AND t.timestamp <= ss.window_end
                    """
                ),
                {"ingredient_lot_id": ingredient_lot_id},
            ).all()

            pallets = s.execute(
                text(
                    """
                    WITH pr AS (
                      SELECT pr.id AS production_run_id
                      FROM production_runs pr
                      WHERE EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(pr.ingredient_lots_used) AS elem
                        WHERE (elem->>'ingredient_lot_id')::uuid = :ingredient_lot_id
                      )
                    ),
                    fpl AS (
                      SELECT fpl.id AS finished_product_lot_id, fpl.finished_product_id
                      FROM finished_product_lots fpl
                      JOIN pr ON pr.production_run_id = fpl.production_run_id
                    )
                    SELECT p.id AS pallet_id, ss.store_id, fpl.finished_product_id
                    FROM pallets p
                    JOIN fpl ON fpl.finished_product_lot_id = p.finished_product_lot_id
                    JOIN store_shipments ss ON ss.id = p.store_shipment_id
                    """
                ),
                {"ingredient_lot_id": ingredient_lot_id},
            ).all()

        affected_pallet_ids = list({r[0] for r in pallets})
        affected_store_ids = list({r[1] for r in pallets})
        affected_product_ids = list({r[2] for r in pallets})
        affected_pallet_set = set(affected_pallet_ids)

        # For seeded demo data, all pallets of the impacted lots are contaminated.
        affected_pallets = [AffectedPallet(pallet_id=pid, certainty=1.0) for pid in affected_pallet_ids]

        # Compute peak stock fraction using deterministic inventory composition probabilities.
        ts_by_store: dict[uuid.UUID, list[datetime]] = {}
        for _, store_id, ts in tx_rows:
            ts_by_store.setdefault(store_id, []).append(ts.astimezone(UTC))

        # If there are no transactions (rare), fall back to shipped/arrived timestamps for impacted pallets.
        if not ts_by_store and affected_store_ids and affected_product_ids:
            with self.session_factory() as s:
                rows = s.execute(
                    text(
                        """
                        SELECT ss.store_id, ss.shipped_at, COALESCE(ss.arrived_at, ss.shipped_at) AS arrived_at
                        FROM pallets p
                        JOIN store_shipments ss ON ss.id = p.store_shipment_id
                        WHERE p.id = ANY(CAST(:pallet_ids AS uuid[]))
                        """
                    ),
                    {"pallet_ids": affected_pallet_ids},
                ).all()
            for store_id, shipped_at, arrived_at in rows:
                ts_by_store.setdefault(store_id, []).extend([shipped_at.astimezone(UTC), arrived_at.astimezone(UTC)])

        store_peaks: dict[uuid.UUID, float] = {}
        for store_id, times in ts_by_store.items():
            # De-duplicate and cap for performance.
            # Keep a mix of early + late times so peak computation can observe state transitions
            # (e.g., 100% affected before clean stock arrives, then mixed/clean later).
            uniq_all = sorted({t.replace(microsecond=0) for t in times})
            uniq = (uniq_all[:200] + uniq_all[-200:]) if len(uniq_all) > 400 else uniq_all
            store_peaks[store_id] = self._compute_peak_affected_fraction(
                comp=comp,
                store_id=store_id,
                product_ids=affected_product_ids,
                affected_pallet_ids=affected_pallet_set,
                candidate_times=uniq,
            )

        affected_stores = [
            AffectedStore(store_id=sid, affected_stock_fraction_peak=store_peaks.get(sid, 0.0))
            for sid in affected_store_ids
        ]

        tx_by_store: dict[uuid.UUID, list[uuid.UUID]] = {}
        for tx_id, store_id, ts in tx_rows:
            tx_by_store.setdefault(store_id, []).append(tx_id)

        windows: list[StoreTransactionWindow] = []
        for store_id, tx_ids in tx_by_store.items():
            # Window is derived from the transactions we found.
            tss = [ts.astimezone(UTC) for _, sid, ts in tx_rows if sid == store_id]
            if not tss:
                continue
            start = min(tss)
            end = max(tss)
            windows.append(
                StoreTransactionWindow(
                    store_id=store_id,
                    start_utc=start,
                    end_utc=end,
                    transaction_ids=tx_ids,
                )
            )

        return BlastRadius(
            affected_pallets=affected_pallets,
            affected_stores=affected_stores,
            affected_transactions_window=windows,
            affected_finished_product_ids=affected_product_ids,
        )

    def _build_from_finished_product_lot(self, finished_product_lot_id: uuid.UUID) -> BlastRadius:
        comp = InventoryCompositionEngine(self.session_factory)
        with self.session_factory() as s:
            rows = s.execute(
                text(
                    """
                    SELECT p.id AS pallet_id, ss.store_id, fpl.finished_product_id, ss.shipped_at, COALESCE(ss.arrived_at, ss.shipped_at) AS arrived_at
                    FROM pallets p
                    JOIN finished_product_lots fpl ON fpl.id = p.finished_product_lot_id
                    JOIN store_shipments ss ON ss.id = p.store_shipment_id
                    WHERE fpl.id = :fpl_id
                    """
                ),
                {"fpl_id": finished_product_lot_id},
            ).all()

        pallet_ids = list({r[0] for r in rows})
        store_ids = list({r[1] for r in rows})
        product_ids = list({r[2] for r in rows})
        affected_pallet_set = set(pallet_ids)

        # Window: shipped_at..arrived_at+30d
        windows: list[StoreTransactionWindow] = []
        store_peaks: dict[uuid.UUID, float] = {}
        with self.session_factory() as s:
            for _, store_id, _, shipped_at, arrived_at in rows:
                start = shipped_at.astimezone(UTC)
                end = (arrived_at + timedelta(days=30)).astimezone(UTC)
                tx_ids = s.execute(
                    text(
                        "SELECT id FROM pos_transactions WHERE store_id = :sid AND timestamp >= :st AND timestamp <= :en"
                    ),
                    {"sid": store_id, "st": start, "en": end},
                ).scalars().all()
                # Candidate times: transaction times, falling back to shipped/arrived.
                times = []
                if tx_ids:
                    times = list(
                        s.execute(
                            text(
                                "SELECT timestamp FROM pos_transactions WHERE id = ANY(CAST(:ids AS uuid[]))"
                            ),
                            {"ids": list(tx_ids)},
                        ).scalars().all()
                    )
                if not times:
                    times = [start, arrived_at.astimezone(UTC)]
                uniq = sorted({t.astimezone(UTC).replace(microsecond=0) for t in times})[:250]
                store_peaks[store_id] = self._compute_peak_affected_fraction(
                    comp=comp,
                    store_id=store_id,
                    product_ids=product_ids,
                    affected_pallet_ids=affected_pallet_set,
                    candidate_times=uniq,
                )
                windows.append(
                    StoreTransactionWindow(store_id=store_id, start_utc=start, end_utc=end, transaction_ids=list(tx_ids))
                )

        return BlastRadius(
            affected_pallets=[AffectedPallet(pallet_id=pid, certainty=1.0) for pid in pallet_ids],
            affected_stores=[AffectedStore(store_id=sid, affected_stock_fraction_peak=store_peaks.get(sid, 0.0)) for sid in store_ids],
            affected_transactions_window=windows,
            affected_finished_product_ids=product_ids,
        )

    def _build_from_facility_window(self, facility_id: uuid.UUID, window_start: datetime, window_end: datetime) -> BlastRadius:
        with self.session_factory() as s:
            rows = s.execute(
                text(
                    """
                    WITH pr AS (
                      SELECT pr.id AS production_run_id
                      FROM production_runs pr
                      WHERE pr.facility_id = :facility_id
                        AND pr.started_at >= :window_start
                        AND pr.started_at <= :window_end
                    ),
                    fpl AS (
                      SELECT fpl.id AS finished_product_lot_id, fpl.finished_product_id
                      FROM finished_product_lots fpl
                      JOIN pr ON pr.production_run_id = fpl.production_run_id
                    )
                    SELECT DISTINCT p.id AS pallet_id, ss.store_id, fpl.finished_product_id
                    FROM pallets p
                    JOIN fpl ON fpl.finished_product_lot_id = p.finished_product_lot_id
                    JOIN store_shipments ss ON ss.id = p.store_shipment_id
                    """
                ),
                {"facility_id": facility_id, "window_start": window_start, "window_end": window_end},
            ).all()

        pallet_ids = list({r[0] for r in rows})
        store_ids = list({r[1] for r in rows})
        product_ids = list({r[2] for r in rows})
        windows = [
            StoreTransactionWindow(store_id=sid, start_utc=window_start.astimezone(UTC), end_utc=window_end.astimezone(UTC))
            for sid in store_ids
        ]
        return BlastRadius(
            affected_pallets=[AffectedPallet(pallet_id=pid, certainty=0.8) for pid in pallet_ids],
            affected_stores=[AffectedStore(store_id=sid, affected_stock_fraction_peak=0.5) for sid in store_ids],
            affected_transactions_window=windows,
            affected_finished_product_ids=product_ids,
        )
