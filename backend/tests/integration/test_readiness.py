from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from masters_cycling_lab.config import Settings
from masters_cycling_lab.main import create_app
from tests.helpers import FakeEmbedder

MakeSettings = Callable[..., Settings]


def test_ready_once_migrated(migrated_database: str, make_settings: MakeSettings) -> None:
    settings = make_settings(database_url=migrated_database)
    app = create_app(settings)
    app.state.embedder = FakeEmbedder(settings)  # stands in for a loaded model
    client = TestClient(app)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "migrations": "ok",
            "vector_extension": "ok",
            "storage": "ok",
            "embedding_model": "ok",
        },
        "llm": "not_configured",
    }


def test_not_ready_before_migrations(empty_database: str, make_settings: MakeSettings) -> None:
    client = TestClient(create_app(make_settings(database_url=empty_database)))

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    checks = response.json()["error"]["details"]["checks"]
    assert checks["database"] == "ok"
    assert "run make migrate" in checks["migrations"]
    assert checks["vector_extension"] == "missing"


def test_llm_settings_are_reported_without_calling_the_provider(
    migrated_database: str, make_settings: MakeSettings
) -> None:
    # The base URL points nowhere; readiness must still pass because it never contacts the provider.
    settings = make_settings(database_url=migrated_database, llm_base_url="http://127.0.0.1:1/v1", llm_model="any")
    app = create_app(settings)
    app.state.embedder = FakeEmbedder(settings)
    response = TestClient(app).get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["llm"] == "configured"


def test_not_ready_without_the_embedding_model(
    migrated_database: str, make_settings: MakeSettings, tmp_path: Path
) -> None:
    client = TestClient(create_app(make_settings(database_url=migrated_database, model_cache_dir=tmp_path)))
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert "make download-model" in response.json()["error"]["details"]["checks"]["embedding_model"]
