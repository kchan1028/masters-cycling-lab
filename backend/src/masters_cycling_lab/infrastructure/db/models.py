"""Database tables.

The Alembic migrations create the schema; these classes must match them (tests/integration/test_migrations.py
checks this). Most invariants are enforced by the database itself so that a bug in application code fails loudly
instead of storing inconsistent data.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

import numpy as np
import numpy.typing as npt
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# The vector column has a fixed size. A model with another dimension needs a migration and a full reindex.
EMBEDDING_DIMENSION = 384

UuidPk = Annotated[
    uuid.UUID, mapped_column(primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
]
CreatedAt = Annotated[datetime, mapped_column(server_default=func.now())]
TextList = Annotated[list[str], mapped_column(ARRAY(Text), server_default="{}")]
JsonObject = Annotated[dict[str, Any], mapped_column(server_default=text("'{}'::jsonb"))]


def is_sha256(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} ~ '^[0-9a-f]{{64}}$'", name=f"{column}_is_sha256")


def one_of(column: str, values: tuple[str, ...]) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} in ({allowed})", name=f"{column}_valid")


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {
        str: Text(),
        datetime: DateTime(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
        dict[str, Any]: JSONB(),
    }


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UuidPk]
    original_filename: Mapped[str]
    storage_key: Mapped[str] = mapped_column(unique=True)
    sha256: Mapped[str]
    byte_size: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None]

    # Bibliographic metadata. metadata_source says how far it can be trusted; PDF metadata is never "verified".
    title: Mapped[str | None]
    authors: Mapped[TextList]
    publication_year: Mapped[int | None] = mapped_column(SmallInteger)
    doi: Mapped[str | None]
    source_url: Mapped[str | None]
    license: Mapped[str | None]
    access_status: Mapped[str] = mapped_column(server_default="unknown")
    metadata_source: Mapped[str] = mapped_column(server_default="extracted_unverified")

    active_index_version_id: Mapped[uuid.UUID | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    # Set the moment a delete is requested, which hides the document from retrieval before its data is purged.
    deleted_at: Mapped[datetime | None]

    __table_args__ = (
        is_sha256("sha256"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("length(original_filename) between 1 and 255", name="filename_length"),
        CheckConstraint("page_count > 0", name="page_count_positive"),
        CheckConstraint("publication_year between 1800 and 2100", name="publication_year_range"),
        one_of("access_status", ("open_access", "user_provided", "restricted", "unknown")),
        one_of("metadata_source", ("user_supplied", "manifest_verified", "extracted_unverified")),
        # The active index must be one of this document's own index versions.
        ForeignKeyConstraint(
            ["id", "active_index_version_id"],
            ["index_versions.document_id", "index_versions.id"],
            use_alter=True,
            name="fk_documents_active_index_version",
        ),
        # The same file can be uploaded again once its earlier document has been deleted.
        Index("uq_documents_sha256_not_deleted", "sha256", unique=True, postgresql_where=text("deleted_at is null")),
    )


class IndexVersion(Base):
    """One complete extraction + chunking + embedding of a document. Built separately, then activated."""

    __tablename__ = "index_versions"

    id: Mapped[UuidPk]
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(server_default="building")
    file_sha256: Mapped[str]
    extractor: Mapped[str]
    extractor_version: Mapped[str]
    chunking_config: Mapped[dict[str, Any]]
    chunking_hash: Mapped[str]
    embedding_model_id: Mapped[str]
    embedding_model_revision: Mapped[str]
    embedding_dimension: Mapped[int]
    pipeline_fingerprint: Mapped[str]
    page_count: Mapped[int | None]
    chunk_count: Mapped[int | None]
    created_at: Mapped[CreatedAt]
    completed_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("document_id", "id"),
        one_of("status", ("building", "ready", "failed", "retired")),
        CheckConstraint("(status = 'building') = (completed_at is null)", name="completed_at_matches_status"),
        is_sha256("file_sha256"),
        is_sha256("chunking_hash"),
        is_sha256("pipeline_fingerprint"),
        CheckConstraint("embedding_model_revision ~ '^[0-9a-f]{40}$'", name="revision_is_commit_hash"),
        CheckConstraint(f"embedding_dimension = {EMBEDDING_DIMENSION}", name="dimension_matches_column"),
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[UuidPk]
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(server_default="queued")
    stage: Mapped[str | None]
    progress_done: Mapped[int] = mapped_column(server_default="0")
    progress_total: Mapped[int | None]
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    max_attempts: Mapped[int] = mapped_column(server_default="3")
    available_after: Mapped[datetime] = mapped_column(server_default=func.now())

    # Lease. claim_token changes on every claim; writes check it so a worker that lost the lease cannot publish.
    worker_id: Mapped[str | None]
    claim_token: Mapped[uuid.UUID | None]
    lease_expires_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]

    # Safe to show to the user: a stable code and a short message, never a traceback.
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]

    requested_config: Mapped[JsonObject]
    # The version this job built. Cleared when an old version is cleaned up; the job's history stays.
    index_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("index_versions.id", ondelete="SET NULL"))
    created_at: Mapped[CreatedAt]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    __table_args__ = (
        one_of("status", ("queued", "running", "succeeded", "failed", "canceled")),
        one_of("stage", ("extracting", "chunking", "embedding", "activating")),
        CheckConstraint(
            "progress_done >= 0 and (progress_total is null or progress_done <= progress_total)", name="progress_valid"
        ),
        CheckConstraint("attempt_count between 0 and max_attempts and max_attempts >= 1", name="attempts_valid"),
        CheckConstraint(
            "status <> 'running' or "
            "(claim_token is not null and worker_id is not null and lease_expires_at is not null)",
            name="running_has_lease",
        ),
        CheckConstraint(
            "(status in ('succeeded', 'failed', 'canceled')) = (finished_at is not null)",
            name="finished_at_matches_status",
        ),
        CheckConstraint("status <> 'failed' or error_code is not null", name="failed_has_error_code"),
        # At most one queued or running job per document.
        Index(
            "uq_ingestion_jobs_one_active_per_document",
            "document_id",
            unique=True,
            postgresql_where=text("status in ('queued', 'running')"),
        ),
        Index("ix_ingestion_jobs_claimable", "available_after", postgresql_where=text("status = 'queued'")),
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[UuidPk]
    index_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("index_versions.id", ondelete="CASCADE"))
    # Physical page in the PDF, starting at 1. The printed label ("iv", "S12") is kept separately.
    page_number: Mapped[int]
    page_label: Mapped[str | None]
    text: Mapped[str]
    warnings: Mapped[TextList]

    __table_args__ = (
        UniqueConstraint("index_version_id", "page_number"),
        UniqueConstraint("index_version_id", "id"),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[UuidPk]
    index_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("index_versions.id", ondelete="CASCADE"))
    ordinal: Mapped[int]
    text: Mapped[str]
    text_sha256: Mapped[str]
    token_count: Mapped[int]
    section_heading: Mapped[str | None]

    __table_args__ = (
        UniqueConstraint("index_version_id", "ordinal"),
        UniqueConstraint("index_version_id", "id"),
        CheckConstraint("ordinal >= 0", name="ordinal_not_negative"),
        CheckConstraint("length(text) > 0", name="text_not_empty"),
        CheckConstraint("token_count > 0", name="token_count_positive"),
        is_sha256("text_sha256"),
    )


class ChunkSpan(Base):
    """Where a chunk's text came from: [start_offset, end_offset) in one stored page's text."""

    __tablename__ = "chunk_spans"

    id: Mapped[UuidPk]
    index_version_id: Mapped[uuid.UUID]
    chunk_id: Mapped[uuid.UUID]
    page_id: Mapped[uuid.UUID]
    ordinal: Mapped[int]
    start_offset: Mapped[int]
    end_offset: Mapped[int]
    # Text inserted before this span when rebuilding the chunk. Only these exact separators are allowed.
    separator: Mapped[str] = mapped_column(server_default="")

    __table_args__ = (
        # Composite keys keep the chunk and the page in the same index version.
        ForeignKeyConstraint(
            ["index_version_id", "chunk_id"], ["chunks.index_version_id", "chunks.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["index_version_id", "page_id"],
            ["document_pages.index_version_id", "document_pages.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("chunk_id", "ordinal"),
        Index("ix_chunk_spans_page_id", "page_id"),
        CheckConstraint("ordinal >= 0", name="ordinal_not_negative"),
        CheckConstraint("start_offset >= 0 and end_offset > start_offset", name="offsets_valid"),
        CheckConstraint("separator in ('', ' ', chr(10))", name="separator_allowed"),
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True)
    embedding_model_id: Mapped[str]
    embedding_model_revision: Mapped[str]
    embedding: Mapped[npt.NDArray[np.float32]] = mapped_column(Vector(EMBEDDING_DIMENSION))
    created_at: Mapped[CreatedAt]


class QueryRun(Base):
    """One question and everything needed to explain its answer later."""

    __tablename__ = "query_runs"

    id: Mapped[UuidPk]
    question: Mapped[str]
    filters: Mapped[JsonObject]
    retrieval_config: Mapped[JsonObject]
    generation_config: Mapped[dict[str, Any] | None]
    embedding_model_id: Mapped[str]
    embedding_model_revision: Mapped[str]
    llm_model: Mapped[str | None]
    prompt_version: Mapped[str | None]
    index_version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), server_default="{}")
    status: Mapped[str] = mapped_column(server_default="running")
    answer_text: Mapped[str | None]
    limitations: Mapped[TextList]
    error_code: Mapped[str | None]
    timings: Mapped[JsonObject]
    # Only what the provider actually reported. Missing means unknown, not zero.
    usage: Mapped[dict[str, Any] | None]
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        one_of("status", ("running", "answered", "insufficient_evidence", "failed")),
        CheckConstraint("length(question) between 1 and 2000", name="question_length"),
        CheckConstraint("status <> 'answered' or answer_text is not null", name="answered_has_text"),
        CheckConstraint("status <> 'failed' or error_code is not null", name="failed_has_error_code"),
    )


class QueryEvidence(Base):
    """A retrieved candidate, and for selected ones a snapshot of exactly what was sent to the LLM."""

    __tablename__ = "query_evidence"

    id: Mapped[UuidPk]
    query_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("query_runs.id", ondelete="CASCADE"))
    # No cascade: deleting a document must purge the query runs that used it on purpose, not by accident.
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    index_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("index_versions.id", ondelete="SET NULL"))
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"))
    # E1, E2, ... for passages sent to the LLM; empty for candidates that were not selected.
    evidence_label: Mapped[str | None]
    retrieval_rank: Mapped[int]
    cosine_distance: Mapped[float] = mapped_column(Double)
    selected_for_context: Mapped[bool]
    selection_reason: Mapped[str | None]
    passage_text: Mapped[str]
    page_numbers: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    source_metadata: Mapped[JsonObject]

    __table_args__ = (
        UniqueConstraint("query_run_id", "id"),
        UniqueConstraint("query_run_id", "retrieval_rank"),
        UniqueConstraint("query_run_id", "evidence_label"),
        CheckConstraint("retrieval_rank >= 1", name="rank_positive"),
        CheckConstraint("cosine_distance between 0 and 2", name="cosine_distance_range"),
        CheckConstraint("evidence_label ~ '^E[1-9][0-9]*$'", name="evidence_label_format"),
        CheckConstraint("selected_for_context = (evidence_label is not null)", name="label_only_when_selected"),
        CheckConstraint("cardinality(page_numbers) >= 1", name="has_pages"),
    )


class AnswerClaim(Base):
    __tablename__ = "answer_claims"

    id: Mapped[UuidPk]
    query_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("query_runs.id", ondelete="CASCADE"))
    ordinal: Mapped[int]
    text: Mapped[str]

    __table_args__ = (
        UniqueConstraint("query_run_id", "ordinal"),
        UniqueConstraint("query_run_id", "id"),
        CheckConstraint("ordinal >= 0", name="ordinal_not_negative"),
        CheckConstraint("length(text) > 0", name="text_not_empty"),
    )


class AnswerCitation(Base):
    __tablename__ = "answer_citations"

    query_run_id: Mapped[uuid.UUID]
    claim_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)

    __table_args__ = (
        # Both keys include query_run_id, so a claim can only cite evidence from its own query run.
        ForeignKeyConstraint(
            ["query_run_id", "claim_id"], ["answer_claims.query_run_id", "answer_claims.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["query_run_id", "evidence_id"], ["query_evidence.query_run_id", "query_evidence.id"], ondelete="CASCADE"
        ),
    )


class EvaluationRun(Base):
    """A run artifact. The questions and labels themselves live in research/evaluation/*.jsonl under git."""

    __tablename__ = "evaluation_runs"

    id: Mapped[UuidPk]
    split: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="running")
    dataset_sha256: Mapped[str]
    corpus_sha256: Mapped[str]
    config: Mapped[JsonObject]
    code_revision: Mapped[str | None]
    metrics: Mapped[JsonObject]
    started_at: Mapped[CreatedAt]
    finished_at: Mapped[datetime | None]

    __table_args__ = (
        one_of("split", ("train", "dev", "test", "test2")),
        one_of("status", ("running", "completed", "failed")),
        CheckConstraint("(status = 'running') = (finished_at is null)", name="finished_at_matches_status"),
        is_sha256("dataset_sha256"),
        is_sha256("corpus_sha256"),
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[UuidPk]
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"))
    question_id: Mapped[str]
    retrieval: Mapped[JsonObject]
    answer: Mapped[dict[str, Any] | None]
    metrics: Mapped[JsonObject]
    created_at: Mapped[CreatedAt]

    __table_args__ = (UniqueConstraint("evaluation_run_id", "question_id"),)
