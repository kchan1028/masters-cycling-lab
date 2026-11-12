"""Search inputs and results. Distances and scores order results; they are not probabilities of relevance."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

# "hybrid" fuses the vector and lexical rankings. It is evaluated next to the other two; answers use vector search.
SearchMode = Literal["vector", "lexical", "hybrid"]

# Reciprocal rank fusion: a passage scores weight / (RRF_K + rank) in each ranking it appears in. 60 is the usual
# constant. The lexical weight and the depth of each ranking were chosen on the dev split (docs/evaluation.md).
RRF_K = 60
HYBRID_LEXICAL_WEIGHT = 0.5
HYBRID_CANDIDATES = 100


@dataclass(frozen=True)
class SearchFilters:
    document_ids: tuple[uuid.UUID, ...] = ()  # empty means every document
    publication_year_from: int | None = None
    publication_year_to: int | None = None


@dataclass(frozen=True)
class PageSpan:
    page_number: int  # physical page, starting at 1
    page_label: str | None
    start: int  # [start, end) in the stored page text
    end: int


@dataclass(frozen=True)
class SearchHit:
    rank: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    index_version_id: uuid.UUID
    document_title: str | None
    publication_year: int | None
    text: str
    spans: tuple[PageSpan, ...]
    cosine_distance: float | None  # vector search: 0 = same direction, 2 = opposite
    lexical_score: float | None  # lexical search: PostgreSQL ts_rank_cd, higher is better


def fuse(vector: Sequence[SearchHit], lexical: Sequence[SearchHit], k: int) -> list[SearchHit]:
    """Reciprocal rank fusion of two rankings. A passage found by both keeps its distance and its lexical score.

    Equal fused scores keep the order passages were first seen in (vector ranking, then lexical), so the result is as
    stable as its inputs."""
    score: dict[uuid.UUID, float] = {}
    merged: dict[uuid.UUID, SearchHit] = {}
    for rank, hit in enumerate(vector, start=1):
        score[hit.chunk_id] = 1 / (RRF_K + rank)
        merged[hit.chunk_id] = hit
    for rank, hit in enumerate(lexical, start=1):
        score[hit.chunk_id] = score.get(hit.chunk_id, 0.0) + HYBRID_LEXICAL_WEIGHT / (RRF_K + rank)
        found = merged.get(hit.chunk_id)
        merged[hit.chunk_id] = replace(found, lexical_score=hit.lexical_score) if found else hit
    best = sorted(score, key=lambda chunk_id: -score[chunk_id])[:k]  # sorted() is stable
    return [replace(merged[chunk_id], rank=rank) for rank, chunk_id in enumerate(best, start=1)]
