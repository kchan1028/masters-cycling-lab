"""Initial schema: the vector extension and every MVP table.

Revision ID: 8dab1a05061f
Revises:
Create Date: 2026-11-12 06:55:06.186349
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8dab1a05061f"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("authors", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("publication_year", sa.SmallInteger(), nullable=True),
        sa.Column("doi", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("access_status", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("metadata_source", sa.Text(), server_default="extracted_unverified", nullable=False),
        sa.Column("active_index_version_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "access_status in ('open_access', 'user_provided', 'restricted', 'unknown')",
            name=op.f("ck_documents_access_status_valid"),
        ),
        sa.CheckConstraint(
            "metadata_source in ('user_supplied', 'manifest_verified', 'extracted_unverified')",
            name=op.f("ck_documents_metadata_source_valid"),
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_documents_sha256_is_sha256")),
        sa.CheckConstraint("byte_size > 0", name=op.f("ck_documents_byte_size_positive")),
        sa.CheckConstraint("length(original_filename) between 1 and 255", name=op.f("ck_documents_filename_length")),
        sa.CheckConstraint("page_count > 0", name=op.f("ck_documents_page_count_positive")),
        sa.CheckConstraint("publication_year between 1800 and 2100", name=op.f("ck_documents_publication_year_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_documents_storage_key")),
    )
    op.create_index(
        "uq_documents_sha256_not_deleted",
        "documents",
        ["sha256"],
        unique=True,
        postgresql_where=sa.text("deleted_at is null"),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("dataset_sha256", sa.Text(), nullable=False),
        sa.Column("corpus_sha256", sa.Text(), nullable=False),
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("code_revision", sa.Text(), nullable=True),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at is null)", name=op.f("ck_evaluation_runs_finished_at_matches_status")
        ),
        sa.CheckConstraint("corpus_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_evaluation_runs_corpus_sha256_is_sha256")),
        sa.CheckConstraint(
            "dataset_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_evaluation_runs_dataset_sha256_is_sha256")
        ),
        sa.CheckConstraint("split in ('train', 'dev', 'test')", name=op.f("ck_evaluation_runs_split_valid")),
        sa.CheckConstraint(
            "status in ('running', 'completed', 'failed')", name=op.f("ck_evaluation_runs_status_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
    )
    op.create_table(
        "query_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "filters", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "retrieval_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("generation_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding_model_id", sa.Text(), nullable=False),
        sa.Column("embedding_model_revision", sa.Text(), nullable=False),
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("index_version_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("limitations", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "timings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status <> 'answered' or answer_text is not null", name=op.f("ck_query_runs_answered_has_text")
        ),
        sa.CheckConstraint(
            "status <> 'failed' or error_code is not null", name=op.f("ck_query_runs_failed_has_error_code")
        ),
        sa.CheckConstraint(
            "status in ('running', 'answered', 'insufficient_evidence', 'failed')",
            name=op.f("ck_query_runs_status_valid"),
        ),
        sa.CheckConstraint("length(question) between 1 and 2000", name=op.f("ck_query_runs_question_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_runs")),
    )
    op.create_table(
        "answer_claims",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("query_run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint("length(text) > 0", name=op.f("ck_answer_claims_text_not_empty")),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_answer_claims_ordinal_not_negative")),
        sa.ForeignKeyConstraint(
            ["query_run_id"], ["query_runs.id"], name=op.f("fk_answer_claims_query_run_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_answer_claims")),
        sa.UniqueConstraint("query_run_id", "id", name=op.f("uq_answer_claims_query_run_id_id")),
        sa.UniqueConstraint("query_run_id", "ordinal", name=op.f("uq_answer_claims_query_run_id_ordinal")),
    )
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("evaluation_run_id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.Text(), nullable=False),
        sa.Column(
            "retrieval", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            name=op.f("fk_evaluation_results_evaluation_run_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_results")),
        sa.UniqueConstraint(
            "evaluation_run_id", "question_id", name=op.f("uq_evaluation_results_evaluation_run_id_question_id")
        ),
    )
    op.create_table(
        "index_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="building", nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column("extractor", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("chunking_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("chunking_hash", sa.Text(), nullable=False),
        sa.Column("embedding_model_id", sa.Text(), nullable=False),
        sa.Column("embedding_model_revision", sa.Text(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("pipeline_fingerprint", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'building') = (completed_at is null)", name=op.f("ck_index_versions_completed_at_matches_status")
        ),
        sa.CheckConstraint("chunking_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_index_versions_chunking_hash_is_sha256")),
        sa.CheckConstraint(
            "embedding_model_revision ~ '^[0-9a-f]{40}$'", name=op.f("ck_index_versions_revision_is_commit_hash")
        ),
        sa.CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_index_versions_file_sha256_is_sha256")),
        sa.CheckConstraint(
            "pipeline_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f("ck_index_versions_pipeline_fingerprint_is_sha256")
        ),
        sa.CheckConstraint(
            "status in ('building', 'ready', 'failed', 'retired')", name=op.f("ck_index_versions_status_valid")
        ),
        sa.CheckConstraint("embedding_dimension = 384", name=op.f("ck_index_versions_dimension_matches_column")),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_index_versions_document_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_index_versions")),
        sa.UniqueConstraint("document_id", "id", name=op.f("uq_index_versions_document_id_id")),
    )
    # documents and index_versions reference each other, so this key is added once both exist.
    # It also makes sure a document's active index is one of its own versions.
    op.create_foreign_key(
        "fk_documents_active_index_version",
        "documents",
        "index_versions",
        ["id", "active_index_version_id"],
        ["document_id", "id"],
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("index_version_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("section_heading", sa.Text(), nullable=True),
        sa.CheckConstraint("text_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_chunks_text_sha256_is_sha256")),
        sa.CheckConstraint("length(text) > 0", name=op.f("ck_chunks_text_not_empty")),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_chunks_ordinal_not_negative")),
        sa.CheckConstraint("token_count > 0", name=op.f("ck_chunks_token_count_positive")),
        sa.ForeignKeyConstraint(
            ["index_version_id"], ["index_versions.id"], name=op.f("fk_chunks_index_version_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("index_version_id", "id", name=op.f("uq_chunks_index_version_id_id")),
        sa.UniqueConstraint("index_version_id", "ordinal", name=op.f("uq_chunks_index_version_id_ordinal")),
    )
    op.create_table(
        "document_pages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("index_version_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("page_label", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("warnings", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.CheckConstraint("page_number >= 1", name=op.f("ck_document_pages_page_number_positive")),
        sa.ForeignKeyConstraint(
            ["index_version_id"],
            ["index_versions.id"],
            name=op.f("fk_document_pages_index_version_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
        sa.UniqueConstraint("index_version_id", "id", name=op.f("uq_document_pages_index_version_id_id")),
        sa.UniqueConstraint(
            "index_version_id", "page_number", name=op.f("uq_document_pages_index_version_id_page_number")
        ),
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("progress_done", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("available_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("claim_token", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "requested_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("index_version_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status in ('succeeded', 'failed', 'canceled')) = (finished_at is not null)",
            name=op.f("ck_ingestion_jobs_finished_at_matches_status"),
        ),
        sa.CheckConstraint(
            "stage in ('extracting', 'chunking', 'embedding', 'activating')", name=op.f("ck_ingestion_jobs_stage_valid")
        ),
        sa.CheckConstraint(
            "status <> 'failed' or error_code is not null", name=op.f("ck_ingestion_jobs_failed_has_error_code")
        ),
        sa.CheckConstraint(
            "status <> 'running' or "
            "(claim_token is not null and worker_id is not null and lease_expires_at is not null)",
            name=op.f("ck_ingestion_jobs_running_has_lease"),
        ),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name=op.f("ck_ingestion_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_count between 0 and max_attempts and max_attempts >= 1",
            name=op.f("ck_ingestion_jobs_attempts_valid"),
        ),
        sa.CheckConstraint(
            "progress_done >= 0 and (progress_total is null or progress_done <= progress_total)",
            name=op.f("ck_ingestion_jobs_progress_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_ingestion_jobs_document_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["index_version_id"],
            ["index_versions.id"],
            name=op.f("fk_ingestion_jobs_index_version_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
    )
    op.create_index(
        "ix_ingestion_jobs_claimable",
        "ingestion_jobs",
        ["available_after"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "uq_ingestion_jobs_one_active_per_document",
        "ingestion_jobs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status in ('queued', 'running')"),
    )
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("embedding_model_id", sa.Text(), nullable=False),
        sa.Column("embedding_model_revision", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["chunks.id"], name=op.f("fk_chunk_embeddings_chunk_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("chunk_id", name=op.f("pk_chunk_embeddings")),
    )
    op.create_table(
        "chunk_spans",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("index_version_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("page_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("separator", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint("separator in ('', ' ', chr(10))", name=op.f("ck_chunk_spans_separator_allowed")),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_chunk_spans_ordinal_not_negative")),
        sa.CheckConstraint(
            "start_offset >= 0 and end_offset > start_offset", name=op.f("ck_chunk_spans_offsets_valid")
        ),
        sa.ForeignKeyConstraint(
            ["index_version_id", "chunk_id"],
            ["chunks.index_version_id", "chunks.id"],
            name=op.f("fk_chunk_spans_index_version_id_chunk_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["index_version_id", "page_id"],
            ["document_pages.index_version_id", "document_pages.id"],
            name=op.f("fk_chunk_spans_index_version_id_page_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunk_spans")),
        sa.UniqueConstraint("chunk_id", "ordinal", name=op.f("uq_chunk_spans_chunk_id_ordinal")),
    )
    op.create_index("ix_chunk_spans_page_id", "chunk_spans", ["page_id"], unique=False)
    op.create_table(
        "query_evidence",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("query_run_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("index_version_id", sa.UUID(), nullable=True),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column("evidence_label", sa.Text(), nullable=True),
        sa.Column("retrieval_rank", sa.Integer(), nullable=False),
        sa.Column("cosine_distance", sa.Double(), nullable=False),
        sa.Column("selected_for_context", sa.Boolean(), nullable=False),
        sa.Column("selection_reason", sa.Text(), nullable=True),
        sa.Column("passage_text", sa.Text(), nullable=False),
        sa.Column("page_numbers", postgresql.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("evidence_label ~ '^E[1-9][0-9]*$'", name=op.f("ck_query_evidence_evidence_label_format")),
        sa.CheckConstraint("cardinality(page_numbers) >= 1", name=op.f("ck_query_evidence_has_pages")),
        sa.CheckConstraint("cosine_distance between 0 and 2", name=op.f("ck_query_evidence_cosine_distance_range")),
        sa.CheckConstraint("retrieval_rank >= 1", name=op.f("ck_query_evidence_rank_positive")),
        sa.CheckConstraint(
            "selected_for_context = (evidence_label is not null)",
            name=op.f("ck_query_evidence_label_only_when_selected"),
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["chunks.id"], name=op.f("fk_query_evidence_chunk_id"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_query_evidence_document_id")),
        sa.ForeignKeyConstraint(
            ["index_version_id"],
            ["index_versions.id"],
            name=op.f("fk_query_evidence_index_version_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["query_run_id"], ["query_runs.id"], name=op.f("fk_query_evidence_query_run_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_evidence")),
        sa.UniqueConstraint(
            "query_run_id", "evidence_label", name=op.f("uq_query_evidence_query_run_id_evidence_label")
        ),
        sa.UniqueConstraint("query_run_id", "id", name=op.f("uq_query_evidence_query_run_id_id")),
        sa.UniqueConstraint(
            "query_run_id", "retrieval_rank", name=op.f("uq_query_evidence_query_run_id_retrieval_rank")
        ),
    )
    op.create_index(op.f("ix_query_evidence_document_id"), "query_evidence", ["document_id"], unique=False)
    op.create_table(
        "answer_citations",
        sa.Column("query_run_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["query_run_id", "claim_id"],
            ["answer_claims.query_run_id", "answer_claims.id"],
            name=op.f("fk_answer_citations_query_run_id_claim_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["query_run_id", "evidence_id"],
            ["query_evidence.query_run_id", "query_evidence.id"],
            name=op.f("fk_answer_citations_query_run_id_evidence_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("claim_id", "evidence_id", name=op.f("pk_answer_citations")),
    )


def downgrade() -> None:
    op.drop_constraint("fk_documents_active_index_version", "documents", type_="foreignkey")
    op.drop_table("answer_citations")
    op.drop_index(op.f("ix_query_evidence_document_id"), table_name="query_evidence")
    op.drop_table("query_evidence")
    op.drop_index("ix_chunk_spans_page_id", table_name="chunk_spans")
    op.drop_table("chunk_spans")
    op.drop_table("chunk_embeddings")
    op.drop_index(
        "uq_ingestion_jobs_one_active_per_document",
        table_name="ingestion_jobs",
        postgresql_where=sa.text("status in ('queued', 'running')"),
    )
    op.drop_index(
        "ix_ingestion_jobs_claimable", table_name="ingestion_jobs", postgresql_where=sa.text("status = 'queued'")
    )
    op.drop_table("ingestion_jobs")
    op.drop_table("document_pages")
    op.drop_table("chunks")
    op.drop_table("index_versions")
    op.drop_table("evaluation_results")
    op.drop_table("answer_claims")
    op.drop_table("query_runs")
    op.drop_table("evaluation_runs")
    op.drop_index(
        "uq_documents_sha256_not_deleted", table_name="documents", postgresql_where=sa.text("deleted_at is null")
    )
    op.drop_table("documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
