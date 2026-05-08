from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

from backend.db.repositories import (
    CustomerRepository,
    InventoryRepository,
    RecallRepository,
    Repositories,
    SupplyChainRepository,
    make_session_factory,
)


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    container = PostgresContainer(
        "postgres:16", username="postgres", password="postgres", dbname="pheromone_test", driver="psycopg"
    )
    with container as c:
        yield c


def _alembic_config(db_url: str) -> Config:
    here = Path(__file__).resolve()
    # repo_root/pheromone/backend/tests/conftest.py -> repo_root/pheromone
    repo_root = here.parents[2]
    ini_path = repo_root / "backend" / "db" / "migrations" / "alembic.ini"

    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(repo_root / "backend" / "db" / "migrations"))
    return cfg


def reset_database(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE;"))
        conn.execute(text("DROP TYPE IF EXISTS contamination_status CASCADE;"))
        conn.execute(text("DROP TYPE IF EXISTS payment_type CASCADE;"))
        conn.execute(text("DROP TYPE IF EXISTS recall_case_state CASCADE;"))
        conn.execute(text("CREATE SCHEMA public;"))
        conn.commit()


@pytest.fixture()
def db_url(postgres_container: PostgresContainer) -> str:
    url = postgres_container.get_connection_url()
    # testcontainers returns postgresql+psycopg2 by default sometimes; normalize for SQLAlchemy+psycopg3
    url = url.replace("postgresql://", "postgresql+psycopg://")
    os.environ["DATABASE_URL"] = url
    return url


@pytest.fixture()
def engine(db_url: str) -> Engine:
    engine = create_engine(db_url, pool_pre_ping=True)
    # Clean schema per test for deterministic fixtures.
    reset_database(engine)
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")
    return engine


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture()
def repos(session_factory: sessionmaker[Session]) -> Repositories:
    return Repositories(
        supply_chain=SupplyChainRepository(session_factory),
        inventory=InventoryRepository(session_factory),
        customers=CustomerRepository(session_factory),
        recalls=RecallRepository(session_factory),
    )
