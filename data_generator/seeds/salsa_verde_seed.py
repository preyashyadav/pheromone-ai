"""
Salsa-Verde demo seed constants.

This file exists so tests can import the scenario's "truth" without copying strings.
"""

from __future__ import annotations

from datetime import datetime, timezone


INGREDIENT_NAME = "roasted_garlic_paste"
INGREDIENT_LOT_CODE = "RG-4429"
MANUFACTURER_NAME = "Sunny Valley Foods"
PLANT_CODE = "P2"
FINISHED_PRODUCT_NAME = "Sunny Valley Salsa Verde 16oz"
FINISHED_PRODUCT_UPC = "0-72440-12345-6"
PRODUCT_LOT_CODES = [f"P2-052126-{c}" for c in ["A", "B", "C", "D", "E", "F"]]

RG4429_WINDOW_START_UTC = datetime(2026, 4, 15, 0, 0, tzinfo=timezone.utc)
RG4429_WINDOW_END_UTC = datetime(2026, 4, 22, 23, 59, tzinfo=timezone.utc)

SHIP_WINDOW_START_UTC = datetime(2026, 4, 17, 0, 0, tzinfo=timezone.utc)
SHIP_WINDOW_END_UTC = datetime(2026, 5, 1, 23, 59, tzinfo=timezone.utc)

DIST_NAME = "Distributor West"
ACME_STORE_NAMES = [f"Acme Store {i}" for i in range(1, 9)]
ACME_AFFECTED_STORE_NAMES = ACME_STORE_NAMES[:6]

