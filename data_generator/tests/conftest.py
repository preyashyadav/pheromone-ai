from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    container = PostgresContainer(
        "postgres:16", username="postgres", password="postgres", dbname="pheromone_gen_test", driver="psycopg"
    )
    with container as c:
        yield c


def _alembic_config(db_url: str) -> Config:
    repo_root = Path(__file__).resolve().parents[2]
    ini_path = repo_root / "backend" / "db" / "migrations" / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(repo_root / "backend" / "db" / "migrations"))
    return cfg


@pytest.fixture()
def db_url(postgres_container: PostgresContainer) -> str:
    url = postgres_container.get_connection_url().replace("postgresql://", "postgresql+psycopg://")
    os.environ["DATABASE_URL"] = url
    return url


@pytest.fixture()
def engine(db_url: str) -> Engine:
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE;"))
        conn.execute(text("DROP TYPE IF EXISTS contamination_status CASCADE;"))
        conn.execute(text("DROP TYPE IF EXISTS payment_type CASCADE;"))
        conn.execute(text("DROP TYPE IF EXISTS recall_case_state CASCADE;"))
        conn.execute(text("CREATE SCHEMA public;"))
    command.upgrade(_alembic_config(db_url), "head")
    return engine

