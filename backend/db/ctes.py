from __future__ import annotations

from sqlalchemy import TextClause, text


def cte_blast_radius_from_ingredient_lot() -> TextClause:
    """
    Given :ingredient_lot_id, returns affected transaction_ids.

    Chain:
      ingredient_lots -> production_runs (ingredient_lots_used JSONB)
      -> finished_product_lots -> pallets -> store_shipments -> stores
      -> pos_transactions (store+time overlap)

    Notes:
    - For Phase 1 tests we return `transaction_id` rows; higher-level agents can
      select additional columns later.
    """
    return text(
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
          SELECT fpl.id AS finished_product_lot_id
          FROM finished_product_lots fpl
          JOIN pr ON pr.production_run_id = fpl.production_run_id
        ),
        pal AS (
          SELECT p.id AS pallet_id, p.store_shipment_id
          FROM pallets p
          JOIN fpl ON fpl.finished_product_lot_id = p.finished_product_lot_id
        ),
        ss AS (
          SELECT ss.id AS store_shipment_id, ss.store_id, ss.shipped_at, COALESCE(ss.arrived_at, ss.shipped_at) AS arrived_at
          FROM store_shipments ss
          JOIN pal ON pal.store_shipment_id = ss.id
        ),
        tx AS (
          SELECT t.id AS transaction_id
          FROM pos_transactions t
          JOIN ss ON ss.store_id = t.store_id
          WHERE t.timestamp >= ss.shipped_at
            AND t.timestamp <= (ss.arrived_at + interval '30 days')
        )
        SELECT transaction_id FROM tx
        """
    )


def cte_blast_radius_from_finished_product_lot() -> TextClause:
    return text(
        """
        WITH pal AS (
          SELECT p.id AS pallet_id, p.store_shipment_id
          FROM pallets p
          WHERE p.finished_product_lot_id = :finished_product_lot_id
        ),
        ss AS (
          SELECT ss.id AS store_shipment_id, ss.store_id, ss.shipped_at, COALESCE(ss.arrived_at, ss.shipped_at) AS arrived_at
          FROM store_shipments ss
          JOIN pal ON pal.store_shipment_id = ss.id
        )
        SELECT t.id AS transaction_id
        FROM pos_transactions t
        JOIN ss ON ss.store_id = t.store_id
        WHERE t.timestamp >= ss.shipped_at
          AND t.timestamp <= (ss.arrived_at + interval '30 days')
        """
    )


def cte_blast_radius_from_facility_window() -> TextClause:
    return text(
        """
        WITH pr AS (
          SELECT pr.id AS production_run_id
          FROM production_runs pr
          WHERE pr.facility_id = :facility_id
            AND pr.started_at >= :window_start
            AND pr.started_at <= :window_end
        ),
        fpl AS (
          SELECT fpl.id AS finished_product_lot_id
          FROM finished_product_lots fpl
          JOIN pr ON pr.production_run_id = fpl.production_run_id
        )
        SELECT DISTINCT t.id AS transaction_id
        FROM pallets p
        JOIN fpl ON fpl.finished_product_lot_id = p.finished_product_lot_id
        JOIN store_shipments ss ON ss.id = p.store_shipment_id
        JOIN pos_transactions t ON t.store_id = ss.store_id
        WHERE t.timestamp >= ss.shipped_at
          AND t.timestamp <= (COALESCE(ss.arrived_at, ss.shipped_at) + interval '30 days')
        """
    )


def cte_inventory_composition_at_time() -> TextClause:
    """
    Returns pallet_id -> units probability mass at a timestamp, for a store+product.

    Uses FIFO-style inventory replay:
      stock adds units to pallet "bins"; sales remove units from bins in time order.

    For Phase 1 tests we compute composition purely from stocking_events and
    pos_transactions line_items.
    """
    return text(
        """
        WITH stock_events AS (
          SELECT
            se.pallet_id,
            se.timestamp,
            se.units_added
          FROM stocking_events se
          WHERE se.store_id = :store_id
            AND se.finished_product_id = :finished_product_id
            AND se.timestamp <= :as_of
        ),
        sales_events AS (
          SELECT
            t.timestamp,
            COALESCE(SUM((li->>'quantity_units')::int), 0) AS units_sold
          FROM pos_transactions t,
               LATERAL jsonb_array_elements(t.line_items) li
          WHERE t.store_id = :store_id
            AND t.timestamp <= :as_of
            AND (li->>'finished_product_id')::uuid = :finished_product_id
          GROUP BY t.timestamp
        ),
        stock_ordered AS (
          SELECT
            pallet_id,
            timestamp,
            units_added,
            SUM(units_added) OVER (ORDER BY timestamp, pallet_id) AS cum_added
          FROM stock_events
        ),
        sales_ordered AS (
          SELECT
            timestamp,
            units_sold,
            SUM(units_sold) OVER (ORDER BY timestamp) AS cum_sold
          FROM sales_events
        ),
        totals AS (
          SELECT
            COALESCE((SELECT MAX(cum_added) FROM stock_ordered), 0) AS total_added,
            COALESCE((SELECT MAX(cum_sold) FROM sales_ordered), 0) AS total_sold
        ),
        remaining_total AS (
          SELECT GREATEST(t.total_added - t.total_sold, 0) AS units_remaining
          FROM totals t
        ),
        remaining_by_event AS (
          SELECT
            so.pallet_id,
            LEAST(so.units_added, GREATEST(so.cum_added - (SELECT total_sold FROM totals), 0))::int AS units_remaining_from_event
          FROM stock_ordered so
        ),
        remaining_by_pallet AS (
          SELECT
            pallet_id,
            SUM(units_remaining_from_event)::int AS units_remaining
          FROM remaining_by_event
          GROUP BY pallet_id
        )
        SELECT
          rbp.pallet_id,
          CASE
            WHEN r.units_remaining = 0 THEN 0.0
            ELSE rbp.units_remaining::float / r.units_remaining::float
          END AS probability
        FROM remaining_by_pallet rbp
        CROSS JOIN remaining_total r
        ORDER BY rbp.pallet_id
        """
    )
