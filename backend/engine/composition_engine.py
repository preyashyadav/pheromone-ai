from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from backend.db.models import InventoryCompositionSnapshot, PosTransaction, StockingEvent


def _floor_hour(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _safe_float(v: Any, *, default: float = 0.0) -> float:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


@dataclass(frozen=True)
class _StockEvent:
    timestamp: datetime
    pallet_id: uuid.UUID
    units_added: int


@dataclass(frozen=True)
class _SaleEvent:
    timestamp: datetime
    units_sold: int


def _apply_proportional_sale(
    pallet_units: dict[uuid.UUID, float], units_sold: int
) -> dict[uuid.UUID, float]:
    if units_sold <= 0:
        return pallet_units
    total = sum(pallet_units.values())
    if total <= 0:
        return pallet_units

    updated: dict[uuid.UUID, float] = {}
    for pallet_id, units in pallet_units.items():
        if units <= 0:
            continue
        frac = units / total
        updated_units = units - (units_sold * frac)
        updated[pallet_id] = max(updated_units, 0.0)
    # Keep zero entries out for cleanliness.
    return {k: v for k, v in updated.items() if v > 1e-9}


def compute_composition_from_events(
    *, stock_events: list[_StockEvent], sale_events: list[_SaleEvent]
) -> dict[uuid.UUID, float]:
    """
    Deterministic composition replay.

    Stocking adds units to specific pallets.
    Sales deplete uniformly across the current mixture (each unit sold has the average composition).
    """
    pallet_units: dict[uuid.UUID, float] = {}
    timeline: list[tuple[datetime, int, Any]] = []
    for se in stock_events:
        timeline.append((se.timestamp, 0, se))
    for sale in sale_events:
        timeline.append((sale.timestamp, 1, sale))
    timeline.sort(key=lambda t: (t[0], t[1]))

    for _, kind, ev in timeline:
        if kind == 0:
            se = ev
            pallet_units[se.pallet_id] = pallet_units.get(se.pallet_id, 0.0) + float(max(se.units_added, 0))
        else:
            sale = ev
            pallet_units = _apply_proportional_sale(pallet_units, int(max(sale.units_sold, 0)))
    total = sum(pallet_units.values())
    if total <= 0:
        return {}
    return {pid: units / total for pid, units in pallet_units.items() if units > 1e-9}


def compute_units_from_events(
    *, stock_events: list[_StockEvent], sale_events: list[_SaleEvent]
) -> dict[uuid.UUID, float]:
    pallet_units: dict[uuid.UUID, float] = {}
    timeline: list[tuple[datetime, int, Any]] = []
    for se in stock_events:
        timeline.append((se.timestamp, 0, se))
    for sale in sale_events:
        timeline.append((sale.timestamp, 1, sale))
    timeline.sort(key=lambda t: (t[0], t[1]))

    for _, kind, ev in timeline:
        if kind == 0:
            se = ev
            pallet_units[se.pallet_id] = pallet_units.get(se.pallet_id, 0.0) + float(max(se.units_added, 0))
        else:
            sale = ev
            pallet_units = _apply_proportional_sale(pallet_units, int(max(sale.units_sold, 0)))
    return {pid: units for pid, units in pallet_units.items() if units > 1e-9}


def apply_events_to_units(
    *,
    starting_units: dict[uuid.UUID, float],
    stock_events: list[_StockEvent],
    sale_events: list[_SaleEvent],
) -> dict[uuid.UUID, float]:
    """
    Replay events starting from an existing pallet->units state.

    This is required for correct handling of sales after a snapshot: sales must
    deplete the *current mixture*, not only newly-stocked units.
    """
    pallet_units: dict[uuid.UUID, float] = {k: float(v) for k, v in starting_units.items() if v > 1e-9}
    timeline: list[tuple[datetime, int, Any]] = []
    for se in stock_events:
        timeline.append((se.timestamp, 0, se))
    for sale in sale_events:
        timeline.append((sale.timestamp, 1, sale))
    timeline.sort(key=lambda t: (t[0], t[1]))

    for _, kind, ev in timeline:
        if kind == 0:
            se = ev
            pallet_units[se.pallet_id] = pallet_units.get(se.pallet_id, 0.0) + float(max(se.units_added, 0))
        else:
            sale = ev
            pallet_units = _apply_proportional_sale(pallet_units, int(max(sale.units_sold, 0)))
    return {pid: units for pid, units in pallet_units.items() if units > 1e-9}


class InventoryCompositionEngine:
    """
    Computes (store, product, time) -> {pallet_id: probability}.

    Uses hourly snapshots persisted in Postgres and a small in-process cache for hot queries.
    """

    def __init__(self, session_factory: sessionmaker[Session], *, max_inproc_cache: int = 256) -> None:
        self._session_factory = session_factory
        self._inproc_cache: dict[tuple[uuid.UUID, uuid.UUID, datetime], dict[uuid.UUID, float]] = {}
        self._max_inproc_cache = max_inproc_cache

    def compute_composition(
        self, store_id: uuid.UUID, product_id: uuid.UUID, at_time: datetime
    ) -> dict[uuid.UUID, float]:
        as_of = at_time.astimezone(UTC)
        snap_hour = _floor_hour(as_of)
        key = (store_id, product_id, snap_hour)
        cached = self._inproc_cache.get(key)
        if cached is None:
            cached = self._load_or_build_snapshot(store_id=store_id, product_id=product_id, snapshot_hour=snap_hour)
            self._remember(key, cached)

        # Apply events after snapshot_hour up to as_of.
        with self._session_factory() as s:
            stock_events = self._load_stock_events(
                s, store_id=store_id, product_id=product_id, start=snap_hour, end=as_of
            )
            sale_events = self._load_sales_events(
                s, store_id=store_id, product_id=product_id, start=snap_hour, end=as_of
            )

        stock = [
            _StockEvent(timestamp=se.timestamp, pallet_id=se.pallet_id, units_added=se.units_added)
            for se in stock_events
        ]
        sales = [_SaleEvent(timestamp=tm, units_sold=units) for tm, units in sale_events]
        pallet_units = apply_events_to_units(starting_units=cached, stock_events=stock, sale_events=sales)
        total = sum(pallet_units.values())
        if total <= 0:
            return {}
        return {pid: units / total for pid, units in pallet_units.items() if units > 1e-9}

    def _remember(self, key: tuple[uuid.UUID, uuid.UUID, datetime], value: dict[uuid.UUID, float]) -> None:
        if len(self._inproc_cache) >= self._max_inproc_cache:
            # Deterministic eviction: pop the first inserted key.
            first = next(iter(self._inproc_cache.keys()))
            self._inproc_cache.pop(first, None)
        self._inproc_cache[key] = value

    def _load_or_build_snapshot(
        self, *, store_id: uuid.UUID, product_id: uuid.UUID, snapshot_hour: datetime
    ) -> dict[uuid.UUID, float]:
        with self._session_factory() as s:
            existing = s.execute(
                select(InventoryCompositionSnapshot.composition).where(
                    InventoryCompositionSnapshot.store_id == store_id,
                    InventoryCompositionSnapshot.finished_product_id == product_id,
                    InventoryCompositionSnapshot.snapshot_hour == snapshot_hour,
                )
            ).scalar_one_or_none()
            if isinstance(existing, dict) and existing:
                return {uuid.UUID(pid): _safe_float(units) for pid, units in existing.items()}

        # Build from scratch up to snapshot_hour.
        with self._session_factory() as s:
            stock_events = self._load_stock_events(s, store_id=store_id, product_id=product_id, start=None, end=snapshot_hour)
            sale_events = self._load_sales_events(s, store_id=store_id, product_id=product_id, start=None, end=snapshot_hour)

        stock = [_StockEvent(timestamp=se.timestamp, pallet_id=se.pallet_id, units_added=se.units_added) for se in stock_events]
        sales = [_SaleEvent(timestamp=tm, units_sold=units) for tm, units in sale_events]
        composition_units = compute_units_from_events(stock_events=stock, sale_events=sales)

        payload = {str(pid): float(units) for pid, units in composition_units.items()}
        with self._session_factory() as s:
            stmt = (
                pg_insert(InventoryCompositionSnapshot)
                .values(
                    store_id=store_id,
                    finished_product_id=product_id,
                    snapshot_hour=snapshot_hour,
                    composition=payload,
                )
                .on_conflict_do_nothing(constraint="uq_composition_snapshot_store_product_hour")
            )
            s.execute(stmt)
            s.commit()
        return composition_units

    def _load_stock_events(
        self,
        s: Session,
        *,
        store_id: uuid.UUID,
        product_id: uuid.UUID,
        start: datetime | None,
        end: datetime,
    ) -> list[StockingEvent]:
        stmt: Select[Any] = select(StockingEvent).where(
            StockingEvent.store_id == store_id,
            StockingEvent.finished_product_id == product_id,
            StockingEvent.timestamp <= end,
        )
        if start is not None:
            stmt = stmt.where(StockingEvent.timestamp > start)
        stmt = stmt.order_by(StockingEvent.timestamp.asc(), StockingEvent.pallet_id.asc())
        return list(s.execute(stmt).scalars().all())

    def _load_sales_events(
        self,
        s: Session,
        *,
        store_id: uuid.UUID,
        product_id: uuid.UUID,
        start: datetime | None,
        end: datetime,
    ) -> list[tuple[datetime, int]]:
        # Unnest line_items and sum quantity_units per timestamp.
        # This intentionally ignores returns; returns are modeled as negative quantities if present.
        params: dict[str, Any] = {"store_id": store_id, "product_id": product_id, "end": end}
        where_start = ""
        if start is not None:
            params["start"] = start
            where_start = "AND t.timestamp > :start"

        rows = s.execute(
            text(
                f"""
                SELECT
                  t.timestamp AS ts,
                  COALESCE(SUM((li->>'quantity_units')::int), 0) AS units_sold
                FROM pos_transactions t,
                     LATERAL jsonb_array_elements(t.line_items) li
                WHERE t.store_id = :store_id
                  AND t.timestamp <= :end
                  {where_start}
                  AND (li->>'finished_product_id')::uuid = :product_id
                GROUP BY t.timestamp
                ORDER BY t.timestamp ASC
                """
            ),
            params,
        ).all()
        return [(r[0], int(r[1])) for r in rows]
