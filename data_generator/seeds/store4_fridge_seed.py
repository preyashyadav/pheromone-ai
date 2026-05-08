"""
Store-4-Fridge demo seed constants.
"""

from __future__ import annotations

from datetime import datetime, timezone


STORE_NAME = "Acme Store 4"
ZONE_NAME = "Store4_Deli_Fridge"

FAILURE_AT_UTC = datetime(2026, 5, 5, 2, 14, tzinfo=timezone.utc)
DISCOVERED_AT_UTC = datetime(2026, 5, 5, 6, 0, tzinfo=timezone.utc)
RESTORED_AT_UTC = datetime(2026, 5, 5, 6, 30, tzinfo=timezone.utc)

