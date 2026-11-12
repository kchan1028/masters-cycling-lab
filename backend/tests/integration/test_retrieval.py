"""Search against real PostgreSQL and pgvector, with the test embedder (a query equal to a chunk's text lands on it)."""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from masters_cycling_lab.application import documents, retrieval
from masters_cycling_lab.domain.retrieval import SearchFilters, SearchMode
from masters_cycling_lab.infrastructure.db.models import Chunk, Document
from masters_cycling_lab.main import create_app
from tests.helpers import FakeEmbedder, make_pdf
from tests.integration.lab import Lab, sample_pdf


def ingest(lab: Lab, pdf: bytes, year: int | None = None) -> uuid.UUID:
    document_id = lab.upload(pdf)
    lab.ingest_next()
    if year is not None:
        with Session(lab.engine) as session:
            session.execute(update(Document).where(Document.id == document_id).values(publication_year=year))
            session.commit()
    return document_id


def a_chunk_text(lab: Lab, document_id: uuid.UUID) -> str:
    with Session(lab.engine) as session:
        version = session.get_one(Document, document_id).active_index_version_id
        query = select(Chunk.text).where(Chunk.index_version_id == version).order_by(Chunk.ordinal)
        return session.scalars(query).first() or ""


def search(
    lab: Lab, query: str, filters: SearchFilters | None = None, mode: SearchMode = "vector"
) -> retrieval.SearchResult:
    with Session(lab.engine) as session:
        return retrieval.search(session, query, filters or SearchFilters(), 10, mode, FakeEmbedder(lab.settings))


def test_closest_chunk_ranks_first_with_distance_increasing(lab: Lab) -> None:
    first = ingest(lab, sample_pdf())
    ingest(lab, make_pdf(["Tapering and carbohydrate loading before long road races."] * 2))
    target = a_chunk_text(lab, first)

    result = search(lab, target)

    assert result.hits[0].text == target
    assert result.hits[0].cosine_distance is not None and result.hits[0].cosine_distance < 1e-5
    distances = [hit.cosine_distance or 0 for hit in result.hits]
    assert distances == sorted(distances)
    assert [hit.rank for hit in result.hits] == list(range(1, len(result.hits) + 1))
    assert result.hits[0].spans[0].page_number >= 1
    assert search(lab, target).hits == result.hits  # same order every time


def test_filters_restrict_documents_and_years(lab: Lab) -> None:
    old = ingest(lab, sample_pdf(), year=2010)
    new = ingest(lab, make_pdf(["Recent study of older riders and recovery."] * 2), year=2024)

    only_new = search(lab, "recovery", SearchFilters(publication_year_from=2020))
    assert {hit.document_id for hit in only_new.hits} == {new}
    assert {hit.document_id for hit in search(lab, "recovery", SearchFilters(document_ids=(old,))).hits} == {old}

    nothing = search(lab, "recovery", SearchFilters(publication_year_from=2030))
    assert (nothing.hits, nothing.searched_documents) == ([], 0)


def test_only_active_ready_documents_are_searched(lab: Lab) -> None:
    ready = ingest(lab, sample_pdf())
    with Session(lab.engine) as session:
        documents.request_ingestion(session, lab.settings, ready)
    lab.ingest_next()  # the rebuild: the first version is retired, the new one active
    lab.upload(make_pdf(["Not indexed yet: masters cyclists recovery."]))  # its job never runs
    with Session(lab.engine) as session:
        active = session.get_one(Document, ready).active_index_version_id

    result = search(lab, "masters cyclists recovery")
    assert {hit.document_id for hit in result.hits} == {ready}
    assert {hit.index_version_id for hit in result.hits} == {active}  # never the retired version

    with Session(lab.engine) as session:
        session.execute(update(Document).where(Document.id == ready).values(deleted_at=datetime.now(UTC)))
        session.commit()
    assert search(lab, "masters cyclists recovery").hits == []


def test_vectors_from_another_model_are_never_compared(lab: Lab) -> None:
    document_id = ingest(lab, sample_pdf())
    other = FakeEmbedder(lab.settings)
    other.revision = "f" * 40
    with Session(lab.engine) as session:
        result = retrieval.search(session, a_chunk_text(lab, document_id), SearchFilters(), 10, "vector", other)
    assert result.hits == []


def test_lexical_baseline_ranks_word_matches(lab: Lab) -> None:
    ingest(lab, sample_pdf())
    result = search(lab, "cadence", mode="lexical")
    assert result.hits and all("cadence" in hit.text.lower() for hit in result.hits)
    scores = [hit.lexical_score or 0 for hit in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert search(lab, "zzzz qqqq", mode="lexical").hits == []


def test_search_endpoint(lab: Lab) -> None:
    document_id = ingest(lab, sample_pdf())
    app = create_app(lab.settings)
    app.state.embedder = FakeEmbedder(lab.settings)
    client = TestClient(app)
    target = a_chunk_text(lab, document_id)

    body = client.post("/api/v1/retrieval/search", json={"query": target, "candidate_k": 3}).json()
    assert len(body["results"]) <= 3 and body["searched_documents"] == 1
    top = body["results"][0]
    assert top["excerpt"] == target and abs(top["similarity"] - (1 - top["cosine_distance"])) < 1e-6
    assert top["pages"][0]["page_number"] >= 1 and "not probabilities" in body["score_note"]

    lexical = client.post("/api/v1/retrieval/search", json={"query": "cadence", "mode": "lexical"}).json()
    assert lexical["embedding_model_id"] is None and lexical["results"][0]["cosine_distance"] is None

    bad = {"query": "x", "filters": {"publication_year_from": 2020, "publication_year_to": 2010}}
    assert client.post("/api/v1/retrieval/search", json=bad).status_code == 422
