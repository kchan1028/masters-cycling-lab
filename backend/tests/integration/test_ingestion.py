"""The ingestion worker against real PostgreSQL and real PDFs, with a fake embedder for speed."""

import io
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from masters_cycling_lab.application import documents
from masters_cycling_lab.application.ingestion import claim_next_job
from masters_cycling_lab.domain.extraction import ExtractedPdf, IngestionProblem
from masters_cycling_lab.infrastructure.db.models import Chunk, ChunkEmbedding, ChunkSpan, DocumentPage, IngestionJob
from tests.helpers import FakeEmbedder
from tests.integration.lab import Lab, sample_pdf


class WorkerKilled(BaseException):
    """Stands in for SIGKILL: nothing in the worker catches it, so the job is left mid-way."""


def test_pdf_reaches_ready_with_traceable_chunks(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    claim = lab.claim()
    lab.runner(claim).run()

    job = lab.job(claim.job_id)
    assert (job.status, job.progress_done) == ("succeeded", job.progress_total)
    document = lab.document(document_id)
    assert document is not None
    [version] = lab.versions(document_id)
    assert document.active_index_version_id == version.id
    assert (version.status, version.page_count, document.page_count) == ("ready", 4, 4)
    assert version.chunk_count is not None and version.chunk_count > 4
    assert document.title == "Recovery in Masters Cyclists"
    assert document.metadata_source == "extracted_unverified"

    with Session(lab.engine) as session:
        pages = {
            p.id: p for p in session.scalars(select(DocumentPage).where(DocumentPage.index_version_id == version.id))
        }
        assert sorted((p.page_number, p.page_label) for p in pages.values()) == [
            (1, "i"),
            (2, "ii"),
            (3, "iii"),
            (4, "iv"),
        ]
        first_page = next(p for p in pages.values() if p.page_number == 1)
        assert "Journal of Masters Cycling" not in first_page.text
        assert any("header" in warning for warning in first_page.warnings)

        rows = session.execute(
            select(Chunk, ChunkSpan)
            .join(ChunkSpan, ChunkSpan.chunk_id == Chunk.id)
            .where(Chunk.index_version_id == version.id)
        ).all()
        assert len(rows) == version.chunk_count
        for chunk, span in rows:
            assert pages[span.page_id].text[span.start_offset : span.end_offset] == chunk.text

        vectors = session.scalars(
            select(ChunkEmbedding.embedding).join(Chunk).where(Chunk.index_version_id == version.id)
        ).all()
        assert len(vectors) == version.chunk_count
        assert all(len(vector) == 384 for vector in vectors)


def test_uploading_the_same_file_again_is_idempotent(lab: Lab) -> None:
    pdf = sample_pdf()
    first = lab.upload(pdf, "first-name.pdf")
    with Session(lab.engine) as session:
        view, duplicate = documents.upload_document(
            session, lab.storage, lab.settings, "second-name.pdf", io.BytesIO(pdf), {}
        )
        jobs = session.scalars(select(IngestionJob).where(IngestionJob.document_id == first)).all()

    assert duplicate
    assert view.document.id == first
    assert view.document.original_filename == "first-name.pdf"
    assert len(jobs) == 1
    assert len(list((lab.settings.storage_root / "files").rglob("*.pdf"))) == 1


def test_stale_worker_cannot_publish_after_its_job_is_taken_over(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    stale = lab.claim("worker-a")
    lab.expire_lease(stale.job_id)
    fresh = lab.claim("worker-b")
    assert (fresh.job_id, fresh.attempt) == (stale.job_id, 2)

    lab.runner(stale).run()
    assert lab.versions(document_id) == []

    lab.runner(fresh).run()
    assert lab.job(fresh.job_id).status == "succeeded"
    assert [v.status for v in lab.versions(document_id)] == ["ready"]


def test_worker_that_loses_its_lease_mid_job_cannot_activate(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    first = lab.claim("worker-a")
    taken_over = []

    def lease_lost_during_embedding(call: int) -> None:
        if call == 1:
            lab.expire_lease(first.job_id)
            taken_over.append(lab.claim("worker-b"))

    lab.runner(first, embedder=FakeEmbedder(lab.settings, on_embed=lease_lost_during_embedding)).run()
    document = lab.document(document_id)
    assert document is not None and document.active_index_version_id is None

    lab.runner(taken_over[0]).run()
    document = lab.document(document_id)
    [version] = lab.versions(document_id)  # worker A's half-built version was cleaned up
    assert document is not None and document.active_index_version_id == version.id


def test_killed_worker_is_recovered_after_its_lease_expires(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    first = lab.claim("worker-a")

    def killed(call: int) -> None:
        raise WorkerKilled

    with pytest.raises(WorkerKilled):
        lab.runner(first, embedder=FakeEmbedder(lab.settings, on_embed=killed)).run()
    assert [v.status for v in lab.versions(document_id)] == ["building"]

    lab.expire_lease(first.job_id)
    lab.ingest_next()

    assert lab.job(first.job_id).status == "succeeded"
    assert [v.status for v in lab.versions(document_id)] == ["ready"]


def test_job_fails_when_its_workers_keep_dying(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    claim = lab.claim()

    def killed(call: int) -> None:
        raise WorkerKilled

    with pytest.raises(WorkerKilled):
        lab.runner(claim, embedder=FakeEmbedder(lab.settings, on_embed=killed)).run()
    with Session(lab.engine) as session:
        session.execute(update(IngestionJob).where(IngestionJob.id == claim.job_id).values(max_attempts=1))
        session.commit()
    lab.expire_lease(claim.job_id)

    assert claim_next_job(lab.engine, "worker-b") is None
    job = lab.job(claim.job_id)
    assert (job.status, job.error_code) == ("failed", "WORKER_LOST")
    assert [v.status for v in lab.versions(document_id)] == ["failed"]


def test_unexpected_error_is_retried_later(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    claim = lab.claim()

    def broken(call: int) -> None:
        raise RuntimeError("model blew up")

    lab.runner(claim, embedder=FakeEmbedder(lab.settings, on_embed=broken)).run()

    job = lab.job(claim.job_id)
    assert (job.status, job.error_code, job.attempt_count) == ("queued", "INGESTION_ERROR", 1)
    assert job.available_after > job.created_at
    assert [v.status for v in lab.versions(document_id)] == ["failed"]
    assert claim_next_job(lab.engine, "worker-b") is None  # not due yet


def test_unusable_pdf_fails_with_a_clear_code(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf(password="secret"))
    claim = lab.claim()
    lab.runner(claim).run()

    job = lab.job(claim.job_id)
    assert (job.status, job.error_code) == ("failed", "PDF_ENCRYPTED")
    assert job.error_message and "password" in job.error_message
    document = lab.document(document_id)
    assert document is not None and document.active_index_version_id is None


def test_failed_reindex_leaves_the_previous_index_searchable(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    lab.ingest_next()
    [original] = lab.versions(document_id)

    with Session(lab.engine) as session:
        documents.request_ingestion(session, lab.settings, document_id)

    def corrupt(path: Path, max_pages: int) -> ExtractedPdf:
        raise IngestionProblem("PDF_CORRUPT", "Damaged.")

    lab.runner(lab.claim(), extract=corrupt).run()

    document = lab.document(document_id)
    assert document is not None and document.active_index_version_id == original.id
    assert [v.status for v in lab.versions(document_id)] == ["ready"]


def test_successful_reindex_swaps_versions_and_retires_the_old_one(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    lab.ingest_next()
    with Session(lab.engine) as session:
        documents.request_ingestion(session, lab.settings, document_id)
    lab.ingest_next()

    old, new = lab.versions(document_id)
    document = lab.document(document_id)
    assert (old.status, new.status) == ("retired", "ready")
    assert document is not None and document.active_index_version_id == new.id


def test_deleting_a_document_during_ingestion_is_safe(lab: Lab) -> None:
    document_id = lab.upload(sample_pdf())
    claim = lab.claim()

    def delete_while_embedding(call: int) -> None:
        if call == 1:
            with Session(lab.engine) as session:
                documents.delete_document(session, lab.storage, document_id)

    lab.runner(claim, embedder=FakeEmbedder(lab.settings, on_embed=delete_while_embedding)).run()

    assert lab.document(document_id) is None
    assert lab.versions(document_id) == []
    with Session(lab.engine) as session:
        assert session.scalars(select(Chunk)).all() == []
    assert list((lab.settings.storage_root / "files").rglob("*.pdf")) == []


def test_job_for_a_different_model_is_refused(lab: Lab) -> None:
    lab.upload(sample_pdf())
    with Session(lab.engine) as session:
        session.execute(
            update(IngestionJob).values(
                requested_config={"embedding_model_id": "other/model", "embedding_model_revision": "0" * 40}
            )
        )
        session.commit()
    claim = lab.claim()
    lab.runner(claim).run()
    assert lab.job(claim.job_id).error_code == "MODEL_MISMATCH"
