"""The database itself must refuse inconsistent data, whatever the application code does."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from masters_cycling_lab.infrastructure.db.models import (
    AnswerCitation,
    AnswerClaim,
    Base,
    Chunk,
    ChunkEmbedding,
    ChunkSpan,
    Document,
    DocumentPage,
    IndexVersion,
    IngestionJob,
    QueryEvidence,
    QueryRun,
)

REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"


def random_sha256() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def add(db: Session, *rows: Base) -> None:
    db.add_all(rows)
    db.flush()


def assert_rejected(db: Session, constraint: str, *rows: Base) -> None:
    """Flushing `rows` (or pending changes) must fail with an error that names `constraint`."""
    with pytest.raises(DBAPIError, match=constraint), db.begin_nested():
        db.add_all(rows)
        db.flush()


def make_document(**values: Any) -> Document:
    defaults: dict[str, Any] = {
        "original_filename": "paper.pdf",
        "storage_key": uuid.uuid4().hex,
        "sha256": random_sha256(),
        "byte_size": 1234,
    }
    return Document(**(defaults | values))


def make_index_version(document_id: uuid.UUID, **values: Any) -> IndexVersion:
    defaults: dict[str, Any] = {
        "document_id": document_id,
        "file_sha256": random_sha256(),
        "extractor": "pymupdf",
        "extractor_version": "1.28.2",
        "chunking_config": {"max_tokens": 300, "overlap_tokens": 40},
        "chunking_hash": random_sha256(),
        "embedding_model_id": "BAAI/bge-small-en-v1.5",
        "embedding_model_revision": REVISION,
        "embedding_dimension": 384,
        "pipeline_fingerprint": random_sha256(),
    }
    return IndexVersion(**(defaults | values))


def make_chunk(index_version_id: uuid.UUID, ordinal: int = 0) -> Chunk:
    return Chunk(
        index_version_id=index_version_id,
        ordinal=ordinal,
        text="Masters cyclists",
        text_sha256=random_sha256(),
        token_count=3,
    )


def make_query_run() -> QueryRun:
    return QueryRun(question="What helps recovery?", embedding_model_id="m", embedding_model_revision=REVISION)


def make_evidence(query_run_id: uuid.UUID, document_id: uuid.UUID, rank: int = 1, **values: Any) -> QueryEvidence:
    defaults: dict[str, Any] = {
        "query_run_id": query_run_id,
        "document_id": document_id,
        "retrieval_rank": rank,
        "cosine_distance": 0.25,
        "selected_for_context": True,
        "evidence_label": f"E{rank}",
        "passage_text": "Older cyclists recovered more slowly.",
        "page_numbers": [3],
    }
    return QueryEvidence(**(defaults | values))


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"sha256": "not-a-hash"}, "ck_documents_sha256_is_sha256"),
        ({"byte_size": 0}, "ck_documents_byte_size_positive"),
        ({"original_filename": ""}, "ck_documents_filename_length"),
        ({"publication_year": 1500}, "ck_documents_publication_year_range"),
        ({"access_status": "leaked"}, "ck_documents_access_status_valid"),
        ({"metadata_source": "verified"}, "ck_documents_metadata_source_valid"),
    ],
)
def test_document_rejects_invalid_values(db: Session, values: dict[str, Any], constraint: str) -> None:
    assert_rejected(db, constraint, make_document(**values))


def test_duplicate_file_is_rejected_until_the_first_copy_is_deleted(db: Session) -> None:
    sha256 = random_sha256()
    first = make_document(sha256=sha256)
    add(db, first)

    assert_rejected(db, "uq_documents_sha256_not_deleted", make_document(sha256=sha256))

    first.deleted_at = datetime.now(UTC)
    add(db, make_document(sha256=sha256))


def test_only_one_active_ingestion_job_per_document(db: Session) -> None:
    document = make_document()
    add(db, document)
    add(db, IngestionJob(document_id=document.id))

    assert_rejected(db, "uq_ingestion_jobs_one_active_per_document", IngestionJob(document_id=document.id))

    finished = IngestionJob(
        document_id=document.id, status="failed", error_code="PDF_ENCRYPTED", finished_at=datetime.now(UTC)
    )
    add(db, finished)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"status": "running"}, "ck_ingestion_jobs_running_has_lease"),
        ({"status": "failed", "finished_at": datetime.now(UTC)}, "ck_ingestion_jobs_failed_has_error_code"),
        ({"status": "succeeded"}, "ck_ingestion_jobs_finished_at_matches_status"),
        ({"attempt_count": 4, "max_attempts": 3}, "ck_ingestion_jobs_attempts_valid"),
        ({"stage": "guessing"}, "ck_ingestion_jobs_stage_valid"),
    ],
)
def test_ingestion_job_state_rules(db: Session, values: dict[str, Any], constraint: str) -> None:
    document = make_document()
    add(db, document)
    assert_rejected(db, constraint, IngestionJob(document_id=document.id, **values))


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"status": "ready"}, "ck_index_versions_completed_at_matches_status"),
        ({"embedding_dimension": 768}, "ck_index_versions_dimension_matches_column"),
        ({"embedding_model_revision": "main"}, "ck_index_versions_revision_is_commit_hash"),
    ],
)
def test_index_version_rules(db: Session, values: dict[str, Any], constraint: str) -> None:
    document = make_document()
    add(db, document)
    assert_rejected(db, constraint, make_index_version(document.id, **values))


def test_active_index_must_be_one_of_the_documents_own_versions(db: Session) -> None:
    mine, other = make_document(), make_document()
    add(db, mine, other)
    my_version, other_version = make_index_version(mine.id), make_index_version(other.id)
    add(db, my_version, other_version)

    mine.active_index_version_id = other_version.id
    assert_rejected(db, "fk_documents_active_index_version")

    mine.active_index_version_id = my_version.id
    db.flush()


def test_embeddings_have_a_fixed_dimension(db: Session) -> None:
    document = make_document()
    add(db, document)
    version = make_index_version(document.id)
    add(db, version)
    chunk, other_chunk = make_chunk(version.id, 0), make_chunk(version.id, 1)
    add(db, chunk, other_chunk)

    wrong_size = ChunkEmbedding(
        chunk_id=chunk.id, embedding_model_id="m", embedding_model_revision=REVISION, embedding=np.zeros(3)
    )
    assert_rejected(db, "expected 384 dimensions", wrong_size)

    vector = np.random.default_rng(0).random(384, dtype=np.float32)
    add(
        db,
        ChunkEmbedding(
            chunk_id=other_chunk.id, embedding_model_id="m", embedding_model_revision=REVISION, embedding=vector
        ),
    )
    stored = db.scalar(select(ChunkEmbedding.embedding).where(ChunkEmbedding.chunk_id == other_chunk.id))
    assert stored is not None
    np.testing.assert_allclose(stored, vector, rtol=1e-6)


def test_chunk_spans_stay_inside_one_index_version(db: Session) -> None:
    document = make_document()
    add(db, document)
    version, other_version = make_index_version(document.id), make_index_version(document.id)
    add(db, version, other_version)
    page = DocumentPage(index_version_id=version.id, page_number=1, text="Masters cyclists recover.")
    other_page = DocumentPage(index_version_id=other_version.id, page_number=1, text="Other text.")
    chunk = make_chunk(version.id)
    add(db, page, other_page, chunk)

    def span(**values: Any) -> ChunkSpan:
        defaults: dict[str, Any] = {
            "index_version_id": version.id,
            "chunk_id": chunk.id,
            "page_id": page.id,
            "ordinal": 0,
            "start_offset": 0,
            "end_offset": 16,
        }
        return ChunkSpan(**(defaults | values))

    assert_rejected(db, "ck_chunk_spans_offsets_valid", span(start_offset=5, end_offset=5))
    assert_rejected(db, "ck_chunk_spans_separator_allowed", span(separator="\t"))
    assert_rejected(db, "fk_chunk_spans_index_version_id_page_id", span(page_id=other_page.id))
    add(db, span())


def test_claims_can_only_cite_evidence_from_their_own_query_run(db: Session) -> None:
    document = make_document()
    run, other_run = make_query_run(), make_query_run()
    add(db, document, run, other_run)
    claim = AnswerClaim(query_run_id=run.id, ordinal=0, text="A supported statement.")
    own_evidence = make_evidence(run.id, document.id)
    other_evidence = make_evidence(other_run.id, document.id)
    add(db, claim, own_evidence, other_evidence)

    citation = AnswerCitation(query_run_id=run.id, claim_id=claim.id, evidence_id=other_evidence.id)
    assert_rejected(db, "fk_answer_citations_query_run_id_evidence_id", citation)

    add(db, AnswerCitation(query_run_id=run.id, claim_id=claim.id, evidence_id=own_evidence.id))


def test_evidence_label_only_on_selected_passages(db: Session) -> None:
    document, run = make_document(), make_query_run()
    add(db, document, run)
    unselected_with_label = make_evidence(run.id, document.id, selected_for_context=False)
    assert_rejected(db, "ck_query_evidence_label_only_when_selected", unselected_with_label)


def test_a_document_used_in_query_history_cannot_be_deleted_by_accident(db: Session) -> None:
    document, run = make_document(), make_query_run()
    add(db, document, run)
    add(db, make_evidence(run.id, document.id))

    with pytest.raises(DBAPIError, match="fk_query_evidence_document_id"), db.begin_nested():
        db.execute(delete(Document).where(Document.id == document.id))


def test_deleting_a_document_removes_its_index_data(db: Session) -> None:
    document = make_document()
    add(db, document)
    version = make_index_version(document.id, status="ready", completed_at=datetime.now(UTC))
    add(db, version)
    page = DocumentPage(index_version_id=version.id, page_number=1, text="Text")
    chunk = make_chunk(version.id)
    add(db, page, chunk)
    add(
        db,
        ChunkSpan(
            index_version_id=version.id, chunk_id=chunk.id, page_id=page.id, ordinal=0, start_offset=0, end_offset=4
        ),
    )
    document.active_index_version_id = version.id
    db.flush()

    db.execute(delete(Document).where(Document.id == document.id))

    for table in (IndexVersion, DocumentPage, Chunk, ChunkSpan):
        assert db.scalar(select(func.count()).select_from(table)) == 0
