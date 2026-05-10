from __future__ import annotations

import os


DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/pheromone"


def get_database_url() -> str:
    """
    Single source of truth for DB URL resolution.

    - Prefer explicit `DATABASE_URL`.
    - Fall back to a sensible local-dev default for dashboard work.
    """
    url = (os.environ.get("DATABASE_URL") or "").strip()
    return url or DEFAULT_DATABASE_URL

