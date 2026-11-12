import pytest
from fastapi.testclient import TestClient

from masters_cycling_lab.config import Settings
from masters_cycling_lab.main import create_app


@pytest.fixture
def client_with_write_route(settings: Settings) -> TestClient:
    app = create_app(settings)

    @app.post("/api/v1/test-write")
    async def write() -> dict[str, bool]:
        return {"written": True}

    return TestClient(app)


def test_unknown_host_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"Host": "attacker.example"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "HOST_NOT_ALLOWED"


def test_allowed_host_with_port_is_accepted(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"Host": "testserver:8080"})
    assert response.status_code == 200


def test_write_from_another_origin_is_rejected(client_with_write_route: TestClient) -> None:
    response = client_with_write_route.post("/api/v1/test-write", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


@pytest.mark.parametrize(
    "headers",
    [
        {},  # curl and other non-browser clients send no Origin
        {"Origin": "http://testserver"},  # same origin
        {"Origin": "http://127.0.0.1:5173"},  # listed in ALLOWED_ORIGINS
    ],
)
def test_write_from_allowed_origins_passes(client_with_write_route: TestClient, headers: dict[str, str]) -> None:
    response = client_with_write_route.post("/api/v1/test-write", headers=headers)
    assert response.status_code == 200


def test_null_origin_cannot_write(client_with_write_route: TestClient) -> None:
    response = client_with_write_route.post("/api/v1/test-write", headers={"Origin": "null"})
    assert response.status_code == 403


def test_reads_from_other_origins_are_not_blocked_but_get_no_cors_header(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
