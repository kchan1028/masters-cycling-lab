"""Fixtures for tests that need a real PostgreSQL with pgvector (`make up`, or `docker compose up -d db`).

Each test session creates throwaway databases next to the one in DATABASE_URL and drops them afterwards,
so these tests never touch your real data.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from masters_cycling_lab.config import Settings
from masters_cycling_lab.infrastructure.db.migrations import upgrade
from masters_cycling_lab.infrastructure.db.models import Base
from masters_cycling_lab.infrastructure.db.session import CONNECT_ARGS, make_engine
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage
from tests.integration.lab import Lab


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/tests/integration/" in str(item.path):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def server_url() -> URL:
    return make_url(Settings().database_url)


@pytest.fixture(scope="session")
def admin_engine(server_url: URL) -> Iterator[Engine]:
    engine = create_engine(server_url, isolation_level="AUTOCOMMIT", connect_args=CONNECT_ARGS)
    # Docker Desktop sometimes stalls a brand-new connection through the published port for several seconds, and
    # every test here depends on this one, so try a few times before giving up.
    for attempt in range(1, 4):
        try:
            with engine.connect():
                break
        except OperationalError:
            if attempt == 3:
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


def empty_all_tables(engine: Engine) -> None:
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def clean_database(migrated_database: str, migrated_engine: Engine) -> Iterator[str]:
    """The migrated test database, empty before and after the test. For tests that commit, like the worker's."""
    empty_all_tables(migrated_engine)
    yield migrated_database
    empty_all_tables(migrated_engine)


@pytest.fixture
def lab(clean_database: str, migrated_engine: Engine, make_settings: Callable[..., Settings]) -> Lab:
    # Small chunks and batches, so a few short pages exercise several chunks and several embedding batches.
    settings = make_settings(
        database_url=clean_database, chunk_max_tokens=20, chunk_overlap_tokens=5, embedding_batch_size=4
    )
    return Lab(settings, migrated_engine, LocalFileStorage(settings.storage_root))


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test, so tests don't see each other's rows."""
    with Session(migrated_engine) as session:
        yield session
        session.rollback()
