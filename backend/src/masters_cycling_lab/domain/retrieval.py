"""Search inputs and results. Distances and scores order results; they are not probabilities of relevance."""

import uuid
from dataclasses import dataclass
from typing import Literal

SearchMode = Literal["vector", "lexical"]


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
