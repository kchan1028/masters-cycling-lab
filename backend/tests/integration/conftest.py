"""Fixtures for tests that need a real PostgreSQL with pgvector (`make up`, or `docker compose up -d db`).

Each test session creates throwaway databases next to the one in DATABASE_URL and drops them afterwards,
so these tests never touch your real data.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from masters_cycling_lab.config import Settings
from masters_cycling_lab.infrastructure.db.migrations import upgrade
from masters_cycling_lab.infrastructure.db.session import make_engine


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/tests/integration/" in str(item.path):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def server_url() -> URL:
    return make_url(Settings().database_url)


@pytest.fixture(scope="session")
def admin_engine(server_url: URL) -> Iterator[Engine]:
    engine = create_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.fail("PostgreSQL is not reachable at DATABASE_URL. Start it with `make up`.", pytrace=False)
    yield engine
    engine.dispose()


def create_database(admin_engine: Engine, server_url: URL) -> str:
    name = f"mcl_test_{uuid.uuid4().hex[:12]}"
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    return server_url.set(database=name).render_as_string(hide_password=False)


def drop_database(admin_engine: Engine, url: str) -> None:
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{make_url(url).database}" WITH (FORCE)'))


@pytest.fixture
def empty_database(admin_engine: Engine, server_url: URL) -> Iterator[str]:
    url = create_database(admin_engine, server_url)
    yield url
    drop_database(admin_engine, url)


@pytest.fixture(scope="session")
def migrated_database(admin_engine: Engine, server_url: URL) -> Iterator[str]:
    url = create_database(admin_engine, server_url)
    upgrade(url)
    yield url
    drop_database(admin_engine, url)


@pytest.fixture(scope="session")
def migrated_engine(migrated_database: str) -> Iterator[Engine]:
    engine = make_engine(migrated_database)
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test, so tests don't see each other's rows."""
    with Session(migrated_engine) as session:
        yield session
        session.rollback()
