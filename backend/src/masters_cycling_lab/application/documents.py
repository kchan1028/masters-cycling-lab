"""Documents: upload, metadata, reindex requests, pages and deletion."""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from masters_cycling_lab.application.errors import Conflict, NotFound, UnsupportedFile, UploadTooLarge
from masters_cycling_lab.application.ingestion import ACTIVE_JOB_STATUSES, requested_pipeline
from masters_cycling_lab.config import Settings
from masters_cycling_lab.infrastructure.db.models import (
    Document,
    DocumentPage,
    IngestionJob,
    QueryEvidence,
    QueryRun,
)
from masters_cycling_lab.infrastructure.storage.local_files import FileTooLarge, LocalFileStorage, StoredFile

METADATA_FIELDS = ("title", "authors", "publication_year", "doi", "source_url", "license", "access_status")
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class DocumentView:
    document: Document
    latest_job: IngestionJob | None


def upload_document(
    session: Session,
    storage: LocalFileStorage,
    settings: Settings,
    filename: str | None,
    source: BinaryIO,
    metadata: Mapping[str, Any],
) -> tuple[DocumentView, bool]:
    """Store a PDF and queue it for ingestion. Returns (view, duplicate).

    Uploading a file that is already in the corpus (same SHA-256) changes nothing and returns the existing
    document, so retries and double clicks are harmless.
    """
    # PDF readers accept the header anywhere in the first 1024 bytes, so do the same. Never trust the extension.
    if b"%PDF-" not in source.read(1024):
        raise UnsupportedFile("NOT_A_PDF", "Only PDF files are accepted, and this file does not look like a PDF.")
    source.seek(0)
    try:
        stored = storage.save(source, settings.max_upload_bytes)
    except FileTooLarge as exc:
        limit_mb = settings.max_upload_bytes / (1024 * 1024)
        raise UploadTooLarge("FILE_TOO_LARGE", f"The file is larger than {limit_mb:g} MB (MAX_UPLOAD_BYTES).") from exc

    try:
        view, duplicate = record_upload(session, settings, stored, filename, metadata)
    except BaseException:
        # A database error after the file was written must not leave a file that no document points to.
        storage.delete(stored.key)
        raise
    if duplicate:
        storage.delete(stored.key)
    return view, duplicate


def record_upload(
    session: Session, settings: Settings, stored: StoredFile, filename: str | None, metadata: Mapping[str, Any]
) -> tuple[DocumentView, bool]:
    existing = find_by_sha256(session, stored.sha256)
    if existing is not None:
        return view_of(session, existing), True

    document = Document(
        original_filename=safe_filename(filename),
        storage_key=stored.key,
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        **{field: value for field, value in metadata.items() if field in METADATA_FIELDS},
    )
    if metadata:
        document.metadata_source = "user_supplied"
    try:
        session.add(document)
        session.flush()
        job = IngestionJob(document_id=document.id, requested_config=requested_pipeline(settings))
        session.add(job)
        session.commit()
    except IntegrityError:
        # The same file was uploaded twice at the same moment and the other request won.
        session.rollback()
        existing = find_by_sha256(session, stored.sha256)
        if existing is None:
            raise
        return view_of(session, existing), True
    return DocumentView(document, job), False


def list_documents(session: Session, limit: int, offset: int) -> tuple[list[DocumentView], int]:
    not_deleted = Document.deleted_at.is_(None)
    total = session.scalar(select(func.count()).select_from(Document).where(not_deleted)) or 0
    documents = session.scalars(
        select(Document)
        .where(not_deleted)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    jobs = latest_jobs(session, [document.id for document in documents])
    return [DocumentView(document, jobs.get(document.id)) for document in documents], total


def get_document(session: Session, document_id: uuid.UUID) -> DocumentView:
    return view_of(session, live_document(session, document_id))


def update_metadata(session: Session, document_id: uuid.UUID, changes: Mapping[str, Any]) -> DocumentView:
    document = live_document(session, document_id)
    for field, value in changes.items():
        if field in METADATA_FIELDS:
            setattr(document, field, value)
    if changes:
        document.metadata_source = "user_supplied"
    session.commit()
    return view_of(session, document)


def request_ingestion(session: Session, settings: Settings, document_id: uuid.UUID) -> IngestionJob:
    """Queue a rebuild. The current index stays searchable until the new one is complete."""
    live_document(session, document_id)
    job = IngestionJob(document_id=document_id, requested_config=requested_pipeline(settings))
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict(
            "INGESTION_ALREADY_ACTIVE", "This document already has a queued or running ingestion job."
        ) from exc
    return job


def get_job(session: Session, job_id: uuid.UUID) -> IngestionJob:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise NotFound("JOB_NOT_FOUND", "No ingestion job with this ID.")
    return job


def get_page(session: Session, document_id: uuid.UUID, page_number: int) -> DocumentPage:
    document = live_document(session, document_id)
    if document.active_index_version_id is None:
        raise Conflict("DOCUMENT_NOT_READY", "The document has not finished indexing.")
    page = session.scalars(
        select(DocumentPage).where(
            DocumentPage.index_version_id == document.active_index_version_id,
            DocumentPage.page_number == page_number,
        )
    ).first()
    if page is None:
        raise NotFound("PAGE_NOT_FOUND", f"Page {page_number} does not exist; the document has {document.page_count}.")
    return page


def delete_document(session: Session, storage: LocalFileStorage, document_id: uuid.UUID) -> None:
    """Hide the document at once, stop its ingestion, then remove its file and everything derived from it.

    Answer history that used the document is deleted too: its stored evidence quotes the document, so keeping it
    would keep the deleted text. Safe to call again if a previous attempt stopped half way.
    """
    document = session.get(Document, document_id)
    if document is None:
        raise NotFound("DOCUMENT_NOT_FOUND", "No document with this ID.")
    storage_key = document.storage_key
    now = datetime.now(UTC)

    # Step 1, committed on its own: hidden from retrieval, and a running worker loses its claim.
    # Job rows are locked before the document row, the same order the worker uses.
    session.execute(
        update(IngestionJob)
        .where(IngestionJob.document_id == document_id, IngestionJob.status.in_(ACTIVE_JOB_STATUSES))
        .values(status="canceled", finished_at=now)
    )
    session.execute(
        update(Document).where(Document.id == document_id, Document.deleted_at.is_(None)).values(deleted_at=now)
    )
    session.commit()

    # Step 2: purge. Cascades remove index versions, pages, chunks, spans, embeddings and jobs.
    session.execute(select(IngestionJob.id).where(IngestionJob.document_id == document_id).with_for_update())
    used_in = select(QueryEvidence.query_run_id).where(QueryEvidence.document_id == document_id)
    session.execute(delete(QueryRun).where(QueryRun.id.in_(used_in)))
    session.execute(delete(Document).where(Document.id == document_id))
    session.commit()
    storage.delete(storage_key)


def live_document(session: Session, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise NotFound("DOCUMENT_NOT_FOUND", "No document with this ID.")
    return document


def find_by_sha256(session: Session, sha256: str) -> Document | None:
    return session.scalars(select(Document).where(Document.sha256 == sha256, Document.deleted_at.is_(None))).first()


def view_of(session: Session, document: Document) -> DocumentView:
    return DocumentView(document, latest_jobs(session, [document.id]).get(document.id))


def latest_jobs(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, IngestionJob]:
    if not document_ids:
        return {}
    jobs = session.scalars(
        select(IngestionJob)
        .where(IngestionJob.document_id.in_(document_ids))
        .order_by(IngestionJob.document_id, IngestionJob.created_at.desc())
        .ext(distinct_on(IngestionJob.document_id))
    )
    return {job.document_id: job for job in jobs}


def safe_filename(filename: str | None) -> str:
    """Keep only the base name, for display. Files are stored under generated keys, never under this name."""
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    name = CONTROL_CHARS.sub("", name).strip()
    return name[:255] or "upload.pdf"
