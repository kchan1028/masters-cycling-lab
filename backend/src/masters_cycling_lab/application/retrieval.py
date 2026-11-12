"""Exact search over active, ready index versions: cosine distance with pgvector, and a lexical baseline.

No approximate index: with a few thousand chunks a full scan is fast, and the results are exact, which makes the
evaluation easier to trust.
"""

import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from masters_cycling_lab.domain.ports import Embedder
from masters_cycling_lab.domain.retrieval import PageSpan, SearchFilters, SearchHit, SearchMode
from masters_cycling_lab.infrastructure.db.models import (
    Chunk,
    ChunkEmbedding,
    ChunkSpan,
    Document,
    DocumentPage,
    IndexVersion,
)

# Ties go to the paper (its file hash) and the chunk's position in it. Both stay the same when the same PDFs are
# ingested again with the same chunking, so results reproduce; chunk IDs are random on every ingest.
TIE_BREAK = (Document.sha256, Chunk.ordinal)


@dataclass
class SearchResult:
    hits: list[SearchHit]
    # Documents that could have matched (searchable and inside the filters). Zero explains an empty result.
    searched_documents: int
    timings_ms: dict[str, float] = field(default_factory=dict)


def search(
    session: Session,
    query: str,
    filters: SearchFilters,
    k: int,
    mode: SearchMode,
    embedder: Embedder | None = None,
) -> SearchResult:
    timings: dict[str, float] = {}
    started = time.perf_counter()
    if mode == "vector":
        if embedder is None:
            raise ValueError("vector search needs an embedder")
        query_vector = embedder.embed_query(query)
        timings["embed_query"] = elapsed_ms(started)
        started = time.perf_counter()
        rows = vector_rows(session, query_vector, filters, k, embedder.model_id, embedder.revision)
    else:
        rows = lexical_rows(session, query, filters, k)
    hits = to_hits(session, rows, mode)
    timings["search"] = elapsed_ms(started)
    return SearchResult(hits, searchable_document_count(session, filters), timings)


def vector_rows(
    session: Session,
    query_vector: npt.NDArray[np.float32],
    filters: SearchFilters,
    k: int,
    model_id: str,
    revision: str,
) -> list[Any]:
    distance = ChunkEmbedding.embedding.cosine_distance(query_vector).label("score")
    query = (
        searchable_chunks(filters)
        .add_columns(distance)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        # Only vectors from the model that embedded the query are comparable.
        .where(ChunkEmbedding.embedding_model_id == model_id, ChunkEmbedding.embedding_model_revision == revision)
        .order_by(distance, *TIE_BREAK)
        .limit(k)
    )
    return list(session.execute(query).all())


def lexical_rows(session: Session, query: str, filters: SearchFilters, k: int) -> list[Any]:
    """A deliberately simple baseline: any query word may match (OR), ranked by PostgreSQL's ts_rank_cd."""
    words = re.findall(r"[a-z0-9]+", query.lower())
    if not words:
        return []
    ts_query = func.to_tsquery("english", " | ".join(words))
    chunk_text = func.to_tsvector("english", Chunk.text)
    score = func.ts_rank_cd(chunk_text, ts_query).label("score")
    query_statement = (
        searchable_chunks(filters)
        .add_columns(score)
        .where(chunk_text.op("@@")(ts_query))
        .order_by(score.desc(), *TIE_BREAK)
        .limit(k)
    )
    return list(session.execute(query_statement).all())


ChunkRow = Select[uuid.UUID, str, uuid.UUID, uuid.UUID, str | None, int | None]


def searchable_chunks(filters: SearchFilters) -> ChunkRow:
    """Chunks of each live document's active index version, and only while that version is ready."""
    return (
        select(Chunk.id, Chunk.text, Chunk.index_version_id, Document.id, Document.title, Document.publication_year)
        .join(Document, Document.active_index_version_id == Chunk.index_version_id)
        .join(IndexVersion, IndexVersion.id == Chunk.index_version_id)
        .where(IndexVersion.status == "ready", Document.deleted_at.is_(None), *filter_clauses(filters))
    )


def filter_clauses(filters: SearchFilters) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if filters.document_ids:
        clauses.append(Document.id.in_(filters.document_ids))
    if filters.publication_year_from is not None:
        clauses.append(Document.publication_year >= filters.publication_year_from)
    if filters.publication_year_to is not None:
        clauses.append(Document.publication_year <= filters.publication_year_to)
    return clauses


def searchable_document_count(session: Session, filters: SearchFilters) -> int:
    query = (
        select(func.count())
        .select_from(Document)
        .join(IndexVersion, IndexVersion.id == Document.active_index_version_id)
        .where(IndexVersion.status == "ready", Document.deleted_at.is_(None), *filter_clauses(filters))
    )
    return session.scalar(query) or 0


def to_hits(session: Session, rows: list[Any], mode: SearchMode) -> list[SearchHit]:
    spans = spans_by_chunk(session, [row[0] for row in rows])
    hits = []
    for rank, (chunk_id, text, version_id, document_id, title, year, score) in enumerate(rows, start=1):
        hits.append(
            SearchHit(
                rank=rank,
                chunk_id=chunk_id,
                document_id=document_id,
                index_version_id=version_id,
                document_title=title,
                publication_year=year,
                text=text,
                spans=tuple(spans[chunk_id]),
                cosine_distance=float(score) if mode == "vector" else None,
                lexical_score=float(score) if mode == "lexical" else None,
            )
        )
    return hits


def spans_by_chunk(session: Session, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PageSpan]]:
    spans: dict[uuid.UUID, list[PageSpan]] = defaultdict(list)
    if not chunk_ids:
        return spans
    rows = session.execute(
        select(
            ChunkSpan.chunk_id,
            DocumentPage.page_number,
            DocumentPage.page_label,
            ChunkSpan.start_offset,
            ChunkSpan.end_offset,
        )
        .join(DocumentPage, DocumentPage.id == ChunkSpan.page_id)
        .where(ChunkSpan.chunk_id.in_(chunk_ids))
        .order_by(ChunkSpan.chunk_id, ChunkSpan.ordinal)
    )
    for chunk_id, page_number, page_label, start, end in rows:
        spans[chunk_id].append(PageSpan(page_number, page_label, start, end))
    return spans


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
