from __future__ import annotations

from alembic import command
from sqlalchemy import create_engine

from backend.tests.conftest import reset_database


def test_alembic_upgrade_head_runs_cleanly(db_url: str) -> None:
    # executed by the `engine` fixture in other tests; validate explicitly here.
    from backend.tests.conftest import _alembic_config

    reset_database(create_engine(db_url))
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")


def test_alembic_downgrade_base_reverses_cleanly(db_url: str) -> None:
    from backend.tests.conftest import _alembic_config

    reset_database(create_engine(db_url))
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
