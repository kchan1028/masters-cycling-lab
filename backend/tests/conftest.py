import pytest
from fastapi.testclient import TestClient

from masters_cycling_lab.config import Settings
from masters_cycling_lab.main import create_app


@pytest.fixture
def settings() -> Settings:
    # Ignore the developer's .env so tests behave the same everywhere.
    return Settings(_env_file=None, app_env="test", database_url="postgresql+psycopg://test@127.0.0.1:1/unused")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)
