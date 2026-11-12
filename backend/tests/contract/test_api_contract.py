import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from masters_cycling_lab.config import Settings
from masters_cycling_lab.main import create_app

OPENAPI_SNAPSHOT = Path(__file__).resolve().parents[2] / "openapi.json"


def assert_error_envelope(response_json: dict[str, object], code: str, request_id: str) -> None:
    error = response_json["error"]
    assert isinstance(error, dict)
    assert error["code"] == code
    assert error["request_id"] == request_id
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], dict)


def test_live_health(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    uuid.UUID(response.headers["X-Request-ID"])


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert_error_envelope(response.json(), "NOT_FOUND", response.headers["X-Request-ID"])


def test_validation_error_hides_submitted_values(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/api/v1/test-validation")
    async def needs_int(limit: int) -> dict[str, int]:
        return {"limit": limit}

    response = TestClient(app).get("/api/v1/test-validation", params={"limit": "secret question text"})
    assert response.status_code == 422
    body = response.json()
    assert_error_envelope(body, "VALIDATION_ERROR", response.headers["X-Request-ID"])
    assert body["error"]["details"]["errors"][0]["location"] == ["query", "limit"]
    assert "secret question text" not in response.text


def test_unexpected_error_is_a_generic_500(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/api/v1/test-crash")
    async def crash() -> None:
        raise RuntimeError("internal detail with a token sk-123")

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/test-crash")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "sk-123" not in response.text
    uuid.UUID(response.json()["error"]["request_id"])


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    preflight = {"Access-Control-Request-Method": "GET"}
    allowed = client.options("/api/v1/health/live", headers={"Origin": "http://127.0.0.1:5173", **preflight})
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

    blocked = client.options("/api/v1/health/live", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in blocked.headers


def test_openapi_snapshot_is_current(settings: Settings) -> None:
    # The frontend types are generated from this file. Run `make api-types` after changing the API.
    current = create_app(settings).openapi()
    assert json.loads(OPENAPI_SNAPSHOT.read_text()) == current
