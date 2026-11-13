"""Durable ingestion: a PostgreSQL job queue with leases, and the pipeline that builds one index version.

Fencing: every write the worker makes happens inside `owned_job`, a transaction that first locks the job row and
checks that this worker's claim token is still current and its lease unexpired. A worker that lost its lease
(stalled, killed and replaced, or its document was deleted) gets LeaseLost on its next write and stops, so it can
never publish stale work. No transaction stays open while the PDF is read or the model runs.

Lock order is always job row first, then document row. Document deletion uses the same order.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy import Engine, and_, delete, func, insert, or_, select, update
from sqlalchemy.orm import Session

from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.chunking import ChunkDraft, ChunkingConfig, chunk_pages, rebuild_text
from masters_cycling_lab.domain.extraction import IngestionProblem, remove_repeated_edge_lines
from masters_cycling_lab.domain.ports import Embedder, PdfExtractor
from masters_cycling_lab.infrastructure.db.models import (
    Chunk,
    ChunkEmbedding,
    ChunkSpan,
    Document,
    DocumentPage,
    IndexVersion,
    IngestionJob,
)
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)
RETRY_BASE_DELAY = timedelta(seconds=30)
ACTIVE_JOB_STATUSES = ("queued", "running")
# Bump these when the text cleanup changes, so the pipeline fingerprint changes with it.
TEXT_CLEANUP = "nfc_whitespace_v1+repeated_edge_lines_v1"


class LeaseLost(Exception):
    """This worker no longer owns the job: its lease expired and was taken over, or the job was canceled."""


@dataclass(frozen=True)
class Claim:
    job_id: uuid.UUID
    document_id: uuid.UUID
    token: uuid.UUID
    attempt: int


def requested_pipeline(settings: Settings) -> dict[str, Any]:
    """Stored on each new job. The worker refuses a job it can't build exactly as requested."""
    return {
        "chunk_max_tokens": settings.chunk_max_tokens,
        "chunk_overlap_tokens": settings.chunk_overlap_tokens,
        "embedding_model_id": settings.embedding_model_id,
        "embedding_model_revision": settings.embedding_model_revision,
    }


def claim_next_job(engine: Engine, worker_id: str, lease: timedelta = LEASE) -> Claim | None:
    """Claim the oldest runnable job: queued and due, or running with an expired lease (its worker died)."""
    with Session(engine) as session, session.begin():
        job = session.scalars(
            select(IngestionJob)
            .where(
                or_(
                    and_(IngestionJob.status == "queued", IngestionJob.available_after <= func.now()),
                    and_(IngestionJob.status == "running", IngestionJob.lease_expires_at < func.now()),
                )
            )
            .order_by(IngestionJob.created_at, IngestionJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if job is None:
            return None

        if job.attempt_count >= job.max_attempts:
            job.status = "failed"
            job.finished_at = datetime.now(UTC)
            job.error_code = "WORKER_LOST"
            job.error_message = "The worker stopped before finishing, too many times."
            session.execute(
                update(IndexVersion)
                .where(IndexVersion.document_id == job.document_id, IndexVersion.status == "building")
                .values(status="failed", completed_at=job.finished_at)
            )
            log.warning("Job %s: giving up after %s lost attempts", job.id, job.attempt_count)
            return None

        claim = Claim(job.id, job.document_id, uuid.uuid4(), job.attempt_count + 1)
        session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job.id)
            .values(
                status="running",
                claim_token=claim.token,
                worker_id=worker_id,
                attempt_count=claim.attempt,
                lease_expires_at=func.now() + lease,
                heartbeat_at=func.now(),
                started_at=func.coalesce(IngestionJob.started_at, func.now()),
                stage=None,
                error_code=None,
                error_message=None,
            )
        )
        return claim


class JobRunner:
    """Runs one claimed job from stored file to active index version."""

    def __init__(
        self,
        engine: Engine,
        storage: LocalFileStorage,
        embedder: Embedder,
        extract_pdf: PdfExtractor,
        settings: Settings,
        claim: Claim,
        lease: timedelta = LEASE,
    ) -> None:
        self.engine = engine
        self.storage = storage
        self.embedder = embedder
        self.extract_pdf = extract_pdf
        self.settings = settings
        self.claim = claim
        self.lease = lease

    def run(self) -> None:
        job_id = self.claim.job_id
        try:
            self.build_index()
            log.info("Job %s: index ready", job_id)
        except LeaseLost:
            log.info("Job %s: lease lost or job canceled; stopped without publishing", job_id)
        except IngestionProblem as problem:
            log.info("Job %s: cannot index this document (%s)", job_id, problem.code)
            self.give_up(problem.code, problem.message)
        except Exception:
            log.exception("Job %s: attempt %s crashed", job_id, self.claim.attempt)
            self.retry_later()

    @contextmanager
    def owned_job(self) -> Iterator[tuple[Session, IngestionJob]]:
        """A transaction that can only commit while this worker still owns the job. It also renews the lease."""
        with Session(self.engine) as session, session.begin():
            job = session.scalars(
                select(IngestionJob)
                .where(
                    IngestionJob.id == self.claim.job_id,
                    IngestionJob.claim_token == self.claim.token,
                    IngestionJob.status == "running",
                    IngestionJob.lease_expires_at > func.now(),
                )
                .with_for_update()
            ).first()
            if job is None:
                raise LeaseLost
            yield session, job
            if job.status == "running":
                session.execute(
                    update(IngestionJob)
                    .where(IngestionJob.id == job.id)
                    .values(lease_expires_at=func.now() + self.lease, heartbeat_at=func.now())
                )

    def build_index(self) -> None:
        with self.owned_job() as (session, job):
            document = session.get_one(Document, self.claim.document_id)
            if document.deleted_at is not None:
                raise LeaseLost
            # A version still "building" can only be left over from an earlier attempt that crashed.
            session.execute(
                delete(IndexVersion).where(IndexVersion.document_id == document.id, IndexVersion.status == "building")
            )
            job.stage = "extracting"
            config = self.chunking_config(job.requested_config)
            file_path = self.storage.path(document.storage_key)
            file_sha256 = document.sha256
            needs_title = document.title is None

        if sha256_of_file(file_path) != file_sha256:
            raise IngestionProblem("FILE_CHANGED", "The stored file no longer matches the checksum taken at upload.")
        extracted = self.extract_pdf(file_path, self.settings.max_pdf_pages)
        pages = remove_repeated_edge_lines(list(extracted.pages))
        chunks = chunk_pages(pages, self.embedder.token_offsets, config)
        if not chunks:
            raise IngestionProblem("NO_TEXT", "No readable text was found in this PDF.")
        self.check_chunks(chunks, {page.page_number: page.text for page in pages})

        version_id = uuid.uuid4()
        chunk_ids = [uuid.uuid4() for _ in chunks]
        page_ids = {page.page_number: uuid.uuid4() for page in pages}
        fingerprint = {
            "extractor": f"{extracted.extractor} {extracted.extractor_version}",
            "text_cleanup": TEXT_CLEANUP,
            "chunking": config.as_dict(),
            "embedding": [self.embedder.model_id, self.embedder.revision, self.embedder.dimension, "normalized"],
        }

        with self.owned_job() as (session, job):
            session.add(
                IndexVersion(
                    id=version_id,
                    document_id=self.claim.document_id,
                    file_sha256=file_sha256,
                    extractor=extracted.extractor,
                    extractor_version=extracted.extractor_version,
                    chunking_config=config.as_dict(),
                    chunking_hash=config.sha256(),
                    embedding_model_id=self.embedder.model_id,
                    embedding_model_revision=self.embedder.revision,
                    embedding_dimension=self.embedder.dimension,
                    pipeline_fingerprint=sha256_of_json(fingerprint),
                    page_count=len(pages),
                    chunk_count=len(chunks),
                )
            )
            session.flush()
            session.execute(
                insert(DocumentPage),
                [
                    {
                        "id": page_ids[page.page_number],
                        "index_version_id": version_id,
                        "page_number": page.page_number,
                        "page_label": page.label,
                        "text": page.text,
                        "warnings": list(page.warnings),
                    }
                    for page in pages
                ],
            )
            session.execute(
                insert(Chunk),
                [
                    {
                        "id": chunk_id,
                        "index_version_id": version_id,
                        "ordinal": chunk.ordinal,
                        "text": chunk.text,
                        "text_sha256": hashlib.sha256(chunk.text.encode()).hexdigest(),
                        "token_count": chunk.token_count,
                    }
                    for chunk, chunk_id in zip(chunks, chunk_ids, strict=True)
                ],
            )
            session.execute(
                insert(ChunkSpan),
                [
                    {
                        "index_version_id": version_id,
                        "chunk_id": chunk_id,
                        "page_id": page_ids[span.page_number],
                        "ordinal": ordinal,
                        "start_offset": span.start,
                        "end_offset": span.end,
                        "separator": span.separator,
                    }
                    for chunk, chunk_id in zip(chunks, chunk_ids, strict=True)
                    for ordinal, span in enumerate(chunk.spans)
                ],
            )
            if needs_title and extracted.title:
                session.get_one(Document, self.claim.document_id).title = extracted.title
            job.stage = "embedding"
            job.progress_total = len(chunks)
            job.progress_done = 0

        batch_size = self.settings.embedding_batch_size
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = self.embedder.embed_documents([chunk.text for chunk in batch])
            self.check_vectors(vectors, len(batch))
            with self.owned_job() as (session, job):
                session.execute(
                    insert(ChunkEmbedding),
                    [
                        {
                            "chunk_id": chunk_ids[chunk.ordinal],
                            "embedding_model_id": self.embedder.model_id,
                            "embedding_model_revision": self.embedder.revision,
                            "embedding": vector,
                        }
                        for chunk, vector in zip(batch, vectors, strict=True)
                    ],
                )
                job.progress_done = start + len(batch)

        with self.owned_job() as (session, job):
            job.stage = "activating"
            embedded = session.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
                .where(Chunk.index_version_id == version_id)
            )
            if embedded != len(chunks):
                raise RuntimeError(f"Expected {len(chunks)} embeddings for version {version_id}, found {embedded}")

            document = session.get_one(Document, self.claim.document_id, with_for_update=True)
            if document.deleted_at is not None:
                raise LeaseLost
            now = datetime.now(UTC)
            if document.active_index_version_id is not None:
                session.execute(
                    update(IndexVersion)
                    .where(IndexVersion.id == document.active_index_version_id)
                    .values(status="retired")
                )
            session.execute(
                update(IndexVersion).where(IndexVersion.id == version_id).values(status="ready", completed_at=now)
            )
            document.active_index_version_id = version_id
            document.page_count = len(pages)
            job.status = "succeeded"
            job.finished_at = now
            job.index_version_id = version_id

    def chunking_config(self, requested: Mapping[str, Any]) -> ChunkingConfig:
        model = (requested.get("embedding_model_id"), requested.get("embedding_model_revision"))
        if model != (None, None) and model != (self.embedder.model_id, self.embedder.revision):
            raise IngestionProblem(
                "MODEL_MISMATCH",
                f"The job asks for {model[0]}@{str(model[1])[:7]}, but the worker runs "
                f"{self.embedder.model_id}@{self.embedder.revision[:7]}. "
                "Vectors from different models are never mixed.",
            )
        config = ChunkingConfig(
            max_tokens=int(requested.get("chunk_max_tokens", self.settings.chunk_max_tokens)),
            overlap_tokens=int(requested.get("chunk_overlap_tokens", self.settings.chunk_overlap_tokens)),
        )
        # The model adds two special tokens ([CLS] and [SEP]) to every input.
        if not 0 <= config.overlap_tokens < config.max_tokens <= self.embedder.max_tokens - 2:
            raise IngestionProblem("BAD_CHUNKING_CONFIG", f"Chunking settings {config.as_dict()} are not usable.")
        return config

    def check_chunks(self, chunks: list[ChunkDraft], page_texts: Mapping[int, str]) -> None:
        for chunk in chunks:
            if rebuild_text(chunk.spans, page_texts) != chunk.text:
                raise RuntimeError(f"Chunk {chunk.ordinal} does not match its page spans")
            # The model would silently cut off anything past its limit, so refuse instead.
            if self.embedder.count_tokens(chunk.text) > self.embedder.max_tokens:
                raise IngestionProblem("CHUNK_TOO_LONG", f"Passage {chunk.ordinal} is longer than the search model accepts.")

    def check_vectors(self, vectors: npt.NDArray[np.float32], expected_rows: int) -> None:
        if vectors.shape != (expected_rows, self.settings.embedding_dimension) or not np.isfinite(vectors).all():
            raise RuntimeError(f"Embedder returned unusable vectors with shape {vectors.shape}")

    def give_up(self, code: str, message: str) -> None:
        try:
            with self.owned_job() as (session, job):
                self.mark_unfinished_version_failed(session)
                job.status = "failed"
                job.finished_at = datetime.now(UTC)
                job.error_code = code
                job.error_message = message
        except LeaseLost:
            pass

    def retry_later(self) -> None:
        try:
            with self.owned_job() as (session, job):
                self.mark_unfinished_version_failed(session)
                job.error_code = "INGESTION_ERROR"
                if job.attempt_count >= job.max_attempts:
                    job.status = "failed"
                    job.finished_at = datetime.now(UTC)
                    job.error_message = f"Processing failed {job.attempt_count} times. The worker log has details."
                else:
                    job.status = "queued"
                    job.available_after = datetime.now(UTC) + RETRY_BASE_DELAY * 2 ** (job.attempt_count - 1)
                    job.lease_expires_at = None
                    job.error_message = f"Attempt {job.attempt_count} failed; it will be retried."
        except LeaseLost:
            pass

    def mark_unfinished_version_failed(self, session: Session) -> None:
        session.execute(
            update(IndexVersion)
            .where(IndexVersion.document_id == self.claim.document_id, IndexVersion.status == "building")
            .values(status="failed", completed_at=datetime.now(UTC))
        )


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def sha256_of_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
