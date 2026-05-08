from __future__ import annotations

from sqlalchemy import text

from data_generator.seeds import salsa_verde_seed


def test_salsa_verde_seed_verification(db_url: str, engine) -> None:
    import subprocess
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    p = subprocess.run(
        [
            str(repo_root / ".venv" / "bin" / "python"),
            str(repo_root / "data_generator" / "generate.py"),
            "--db-url",
            db_url,
            "--seed",
            "42",
            "--scenario",
            "salsa_verde",
            "--reset",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr

    with engine.begin() as conn:
        # Lot exists and contaminated
        row = conn.execute(
            text("SELECT contamination_status FROM ingredient_lots WHERE lot_code = :lot"),
            {"lot": salsa_verde_seed.INGREDIENT_LOT_CODE},
        ).first()
        assert row is not None
        assert row[0] == "confirmed_contaminated"

        # Used only in Plant 2 production runs
        plant2 = conn.execute(
            text(
                """
                SELECT f.id FROM facilities f
                JOIN manufacturers m ON m.id = f.manufacturer_id
                WHERE m.name = :mname AND f.plant_code = :pcode
                """
            ),
            {"mname": salsa_verde_seed.MANUFACTURER_NAME, "pcode": salsa_verde_seed.PLANT_CODE},
        ).scalar_one()

        uses = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM production_runs pr
                WHERE pr.facility_id != :plant2
                  AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements(pr.ingredient_lots_used) e
                    WHERE e->>'ingredient_lot_id' = (
                      SELECT id::text FROM ingredient_lots WHERE lot_code = :lot
                    )
                  )
                """
            ),
            {"plant2": plant2, "lot": salsa_verde_seed.INGREDIENT_LOT_CODE},
        ).scalar_one()
        assert int(uses) == 0

        # Seeded finished product lots exist
        got_lots = conn.execute(
            text("SELECT lot_code FROM finished_product_lots WHERE lot_code = ANY(CAST(:codes AS text[]))"),
            {"codes": salsa_verde_seed.PRODUCT_LOT_CODES},
        ).scalars().all()
        assert set(got_lots) == set(salsa_verde_seed.PRODUCT_LOT_CODES)

        # These lots arrived only at Distributor West (warehouse W1 in our generator)
        west_wh = conn.execute(
            text(
                """
                SELECT w.id
                FROM distributor_warehouses w
                JOIN distributors d ON d.id = w.distributor_id
                WHERE d.name = :dname
                ORDER BY w.name
                LIMIT 1
                """
            ),
            {"dname": salsa_verde_seed.DIST_NAME},
        ).scalar_one()

        other_store_shipments = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM pallets p
                JOIN finished_product_lots fpl ON fpl.id = p.finished_product_lot_id
                JOIN store_shipments ss ON ss.id = p.store_shipment_id
                WHERE fpl.lot_code = ANY(CAST(:codes AS text[]))
                  AND ss.warehouse_id != :west_wh
                """
            ),
            {"codes": salsa_verde_seed.PRODUCT_LOT_CODES, "west_wh": west_wh},
        ).scalar_one()
        assert int(other_store_shipments) == 0

        # Shipped only to 6 specified stores
        allowed_store_ids = set(
            conn.execute(
                text("SELECT id FROM stores WHERE name = ANY(CAST(:names AS text[]))"),
                {"names": salsa_verde_seed.ACME_AFFECTED_STORE_NAMES},
            ).scalars().all()
        )
        seen_store_ids = set(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT ss.store_id
                    FROM pallets p
                    JOIN finished_product_lots fpl ON fpl.id = p.finished_product_lot_id
                    JOIN store_shipments ss ON ss.id = p.store_shipment_id
                    WHERE fpl.lot_code = ANY(CAST(:codes AS text[]))
                    """
                ),
                {"codes": salsa_verde_seed.PRODUCT_LOT_CODES},
            ).scalars().all()
        )
        assert seen_store_ids.issubset(allowed_store_ids)

        # sanity: should cover exactly 6 stores
        assert len(seen_store_ids) == 6

        # >= 1500 transactions of the target UPC in window
        tx_count = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM pos_transactions t, LATERAL jsonb_array_elements(t.line_items) li
                WHERE (li->>'finished_product_id')::uuid = (
                  SELECT id FROM finished_products WHERE upc = :upc
                )
                  AND t.timestamp >= :start
                  AND t.timestamp <= :end
                """
            ),
            {
                "upc": salsa_verde_seed.FINISHED_PRODUCT_UPC,
                "start": salsa_verde_seed.SHIP_WINDOW_START_UTC,
                "end": salsa_verde_seed.SHIP_WINDOW_END_UTC,
            },
        ).scalar_one()
        assert int(tx_count) >= 1500
