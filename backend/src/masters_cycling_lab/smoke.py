"""End-to-end check against a running stack (`make smoke`).

Uploads a small synthetic PDF through the frontend's proxy, waits for the worker, searches it, reads its page and
original file back, asks a question about it and deletes it again. It checks that the pieces work together, not
that answers are any good: that is what the evaluation is for.
"""

import time
import uuid
from typing import Any

import httpx
import pymupdf

INGEST_TIMEOUT_S = 180
QUESTION = "What is this synthetic smoke check page for?"


class SmokeFailure(Exception):
    pass


def run_smoke(base_url: str) -> int:
    uploaded: list[str] = []
    # Answers can take a while with a slow provider; nginx allows 180 s too.
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=180) as client:
        try:
            check_stack(client, uploaded)
        except (SmokeFailure, httpx.HTTPError) as error:
            print(f"FAILED: {error}")
            return 1
        finally:
            for document_id in uploaded:  # only left here when a step failed before the delete step
                try:
                    client.delete(f"/api/v1/documents/{document_id}")
                    print(f"Removed smoke document {document_id}.")
                except httpx.HTTPError:
                    print(f"Could not remove smoke document {document_id}; delete it from the Documents page.")
    print("Smoke check passed.")
    return 0


def check_stack(client: httpx.Client, uploaded: list[str]) -> None:
    home = client.get("/")
    if home.status_code != 200 or 'id="root"' not in home.text:
        raise SmokeFailure(f"The frontend did not serve the app (status {home.status_code}).")
    ok("frontend serves the app")

    expect(client.get("/api/v1/health/ready"), 200)
    ok("API is ready: database migrated, embedding model present")

    marker = uuid.uuid4().hex
    pdf = make_pdf(marker)
    upload = expect(client.post("/api/v1/documents", files={"file": ("smoke-check.pdf", pdf, "application/pdf")}), 202)
    document_id = upload["document"]["id"]
    uploaded.append(document_id)
    ok(f"uploaded document {document_id}")

    wait_until_searchable(client, document_id)
    ok("worker indexed it")

    search = expect(
        client.post("/api/v1/retrieval/search", json={"query": QUESTION, "filters": {"document_ids": [document_id]}}),
        200,
    )
    hits = search["results"]
    if not hits or hits[0]["document_id"] != document_id:
        raise SmokeFailure("Search did not return the uploaded document.")
    ok(f"search found it on page {hits[0]['pages'][0]['page_number']} (distance {hits[0]['cosine_distance']:.3f})")

    page = expect(client.get(f"/api/v1/documents/{document_id}/pages/1"), 200)
    if marker not in page["text"]:
        raise SmokeFailure("The stored page text does not contain the uploaded text.")
    original = client.get(f"/api/v1/documents/{document_id}/file")
    if original.status_code != 200 or original.content != pdf:
        raise SmokeFailure("The stored file does not match the upload.")
    ok("page text and original file match the upload")

    check_answer(client, document_id)

    expect(client.delete(f"/api/v1/documents/{document_id}"), 204)
    expect(client.get(f"/api/v1/documents/{document_id}"), 404)
    uploaded.remove(document_id)
    ok("deleted it again")


def check_answer(client: httpx.Client, document_id: str) -> None:
    response = client.post("/api/v1/answers", json={"question": QUESTION, "filters": {"document_ids": [document_id]}})
    if response.status_code == 503 and "LLM_NOT_CONFIGURED" in response.text:
        # Generation is optional. A configured provider that fails is a real failure, so only this case is skipped.
        print("skip  answer: no LLM provider configured (LLM_NOT_CONFIGURED)")
        return
    answer = expect(response, 200)
    if answer["status"] == "insufficient_evidence":
        ok("answer abstained: not enough evidence")
        return
    if answer["status"] != "answered":
        raise SmokeFailure(f"Unexpected answer status {answer['status']}.")
    cited = {citation["document_id"] for claim in answer["claims"] for citation in claim["citations"]}
    if cited != {document_id}:
        raise SmokeFailure("The answer cites something other than the uploaded document.")
    ok(f"answered with {len(answer['claims'])} cited claims")


def wait_until_searchable(client: httpx.Client, document_id: str) -> None:
    deadline = time.monotonic() + INGEST_TIMEOUT_S
    while time.monotonic() < deadline:
        document = expect(client.get(f"/api/v1/documents/{document_id}"), 200)
        job = document["latest_job"] or {}
        if document["searchable"] and job.get("status") == "succeeded":
            return
        if job.get("status") in ("failed", "canceled"):
            raise SmokeFailure(f"Ingestion {job['status']}: {job.get('error_code')} {job.get('error_message')}")
        time.sleep(1)
    raise SmokeFailure(f"Not searchable after {INGEST_TIMEOUT_S} s. Check the worker: docker compose logs worker")


def make_pdf(marker: str) -> bytes:
    """A one-page PDF. The marker makes every run a new upload instead of a duplicate."""
    document = pymupdf.open()
    page = document.new_page()
    text = (
        f"Smoke check {marker}. This synthetic page is not research. It exists so the smoke check can test upload, "
        "text extraction, chunking, embedding, search, citations and deletion from end to end."
    )
    page.insert_textbox(pymupdf.Rect(50, 50, 560, 800), text, fontsize=11)
    return bytes(document.tobytes())


def expect(response: httpx.Response, status: int) -> Any:
    if response.status_code != status:
        request = f"{response.request.method} {response.request.url.path}"
        raise SmokeFailure(f"{request} returned {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else None


def ok(message: str) -> None:
    print(f"ok    {message}")
