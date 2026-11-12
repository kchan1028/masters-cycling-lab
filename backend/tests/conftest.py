from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from masters_cycling_lab.config import Settings
from masters_cycling_lab.main import create_app

if TYPE_CHECKING:
    from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import (
        SentenceTransformerEmbedder,
    )

# Nothing listens on port 1, so database calls fail fast in tests that must not need PostgreSQL.
UNREACHABLE_DATABASE = "postgresql+psycopg://test@127.0.0.1:1/unused"

MakeSettings = Callable[..., Settings]


@pytest.fixture
def make_settings(tmp_path: Path) -> MakeSettings:
    def make(**overrides: Any) -> Settings:
        # Ignore the developer's .env so tests behave the same everywhere. TestClient sends Host: testserver.
        values: dict[str, Any] = {
            "app_env": "test",
            "database_url": UNREACHABLE_DATABASE,
            "storage_root": tmp_path / "storage",
            "allowed_hosts": ["testserver"],
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return make


@pytest.fixture
def settings(make_settings: MakeSettings) -> Settings:
    return make_settings()


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture(scope="session")
def real_embedder() -> "SentenceTransformerEmbedder":
    """The real pinned model, loaded once per test run. Only tests marked `model` should ask for it."""
    from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import (
        SentenceTransformerEmbedder,
    )

    return SentenceTransformerEmbedder(Settings(_env_file=None, database_url=UNREACHABLE_DATABASE), allow_download=True)
