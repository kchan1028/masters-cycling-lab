"""The document endpoints, through HTTP, against real PostgreSQL and real storage."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from masters_cycling_lab.config import Settings
from masters_cycling_lab.main import create_app
from tests.integration.lab import Lab, sample_pdf


@pytest.fixture
def client(lab: Lab) -> TestClient:
    return TestClient(create_app(lab.settings))


def upload(client: TestClient, content: bytes, name: str = "paper.pdf", **form: str) -> dict[str, Any]:
    response = client.post("/api/v1/documents", files={"file": (name, content, "application/pdf")}, data=form)
    return {"status": response.status_code, **response.json()}


def test_upload_queues_ingestion_and_a_repeat_is_a_duplicate(client: TestClient) -> None:
    pdf = sample_pdf()
    first = upload(client, pdf)
    again = upload(client, pdf, name="renamed.pdf")

    assert first["status"] == 202 and not first["duplicate"]
    assert first["document"]["searchable"] is False
    assert first["document"]["latest_job"]["status"] == "queued"
    assert again["status"] == 200 and again["duplicate"]
    assert again["document"]["id"] == first["document"]["id"]


def test_upload_checks_the_content_not_the_name(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents", files={"file": ("paper.pdf", b"<html>not a pdf</html>", "application/pdf")}
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "NOT_A_PDF"


def test_upload_over_the_size_limit_is_rejected(lab: Lab, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(database_url=lab.settings.database_url, max_upload_bytes=500)
    client = TestClient(create_app(settings))
    response = client.post("/api/v1/documents", files={"file": ("big.pdf", sample_pdf(), "application/pdf")})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert list(settings.storage_root.rglob("*.pdf")) == []


def test_supplied_metadata_is_marked_as_user_supplied(client: TestClient) -> None:
    body = upload(client, sample_pdf(), title="Given title", doi="10.1123/japa.2020-0001", publication_year="2021")
    document = body["document"]
    assert (document["title"], document["doi"], document["publication_year"]) == (
        "Given title",
        "10.1123/japa.2020-0001",
        2021,
    )
    assert document["metadata_source"] == "user_supplied"


def test_list_get_and_correct_metadata(client: TestClient) -> None:
    document_id = upload(client, sample_pdf())["document"]["id"]

    listing = client.get("/api/v1/documents").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == document_id

    patched = client.patch(
        f"/api/v1/documents/{document_id}",
        json={"title": "Corrected title", "authors": ["A. Rider", "B. Coach"], "access_status": "open_access"},
    )
    assert patched.status_code == 200
    assert patched.json()["authors"] == ["A. Rider", "B. Coach"]
    assert patched.json()["metadata_source"] == "user_supplied"
    assert client.get(f"/api/v1/documents/{document_id}").json()["title"] == "Corrected title"


def test_invalid_metadata_is_rejected(client: TestClient) -> None:
    document_id = upload(client, sample_pdf())["document"]["id"]
    response = client.patch(f"/api/v1/documents/{document_id}", json={"doi": "not-a-doi", "unknown": 1})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_pages_and_the_original_file_after_ingestion(lab: Lab, client: TestClient) -> None:
    original = sample_pdf()
    document_id = upload(client, original)["document"]["id"]
    assert client.get(f"/api/v1/documents/{document_id}/pages/1").json()["error"]["code"] == "DOCUMENT_NOT_READY"

    lab.ingest_next()

    document = client.get(f"/api/v1/documents/{document_id}").json()
    assert document["searchable"] is True and document["latest_job"]["status"] == "succeeded"
    page = client.get(f"/api/v1/documents/{document_id}/pages/2").json()
    assert (page["page_number"], page["page_label"]) == (2, "ii")
    assert "Sentence 2.0" in page["text"]
    assert client.get(f"/api/v1/documents/{document_id}/pages/9").status_code == 404

    pdf = client.get(f"/api/v1/documents/{document_id}/file")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content == original


def test_reindex_is_refused_while_a_job_is_active(lab: Lab, client: TestClient) -> None:
    document_id = upload(client, sample_pdf())["document"]["id"]
    busy = client.post(f"/api/v1/documents/{document_id}/ingestions")
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "INGESTION_ALREADY_ACTIVE"

    lab.ingest_next()
    job = client.post(f"/api/v1/documents/{document_id}/ingestions")
    assert job.status_code == 202
    assert client.get(f"/api/v1/ingestion-jobs/{job.json()['id']}").json()["status"] == "queued"


def test_delete_removes_the_document_its_file_and_its_index(lab: Lab, client: TestClient) -> None:
    document_id = upload(client, sample_pdf())["document"]["id"]
    lab.ingest_next()

    assert client.delete(f"/api/v1/documents/{document_id}").status_code == 204
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 404
    assert client.get("/api/v1/documents").json()["total"] == 0
    assert list(lab.settings.storage_root.rglob("*.pdf")) == []
    assert lab.versions(uuid.UUID(document_id)) == []


def test_unknown_ids_are_404(client: TestClient) -> None:
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/documents/{missing}").json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert client.get(f"/api/v1/ingestion-jobs/{missing}").json()["error"]["code"] == "JOB_NOT_FOUND"
    assert client.delete(f"/api/v1/documents/{missing}").status_code == 404
