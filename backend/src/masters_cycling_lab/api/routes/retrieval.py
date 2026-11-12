import uuid
from typing import Self

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from masters_cycling_lab.api.dependencies import SessionDep, SettingsDep, query_embedder
from masters_cycling_lab.application import retrieval
from masters_cycling_lab.domain.retrieval import SearchFilters, SearchHit, SearchMode

router = APIRouter(prefix="/retrieval", tags=["retrieval"])

SCORE_NOTE = (
    "Cosine distance (lower is closer) and similarity (1 - distance) only order the results. "
    "They are not probabilities that a passage is relevant or correct."
)


class FiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An empty list means every document.
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    publication_year_from: int | None = Field(default=None, ge=1800, le=2100)
    publication_year_to: int | None = Field(default=None, ge=1800, le=2100)

    @model_validator(mode="after")
    def years_in_order(self) -> Self:
        start, end = self.publication_year_from, self.publication_year_to
        if start is not None and end is not None and start > end:
            raise ValueError("publication_year_from must not be after publication_year_to")
        return self


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    candidate_k: int | None = Field(default=None, ge=1, le=100, description="Defaults to RETRIEVAL_CANDIDATE_K")
    mode: SearchMode = "vector"
    filters: FiltersIn = Field(default_factory=FiltersIn)


class PageRef(BaseModel):
    page_number: int  # physical page in the PDF, starting at 1
    page_label: str | None
    start_offset: int  # [start, end) in the stored text of that page
    end_offset: int


class SearchResultOut(BaseModel):
    rank: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    index_version_id: uuid.UUID
    document_title: str | None
    publication_year: int | None
    pages: list[PageRef]
    excerpt: str
    cosine_distance: float | None
    similarity: float | None
    lexical_score: float | None

    @classmethod
    def from_hit(cls, hit: SearchHit) -> "SearchResultOut":
        distance = hit.cosine_distance
        pages = [PageRef(page_number=s.page_number, page_label=s.page_label, start_offset=s.start, end_offset=s.end)
                 for s in hit.spans]  # fmt: skip
        return cls(
            rank=hit.rank,
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            index_version_id=hit.index_version_id,
            document_title=hit.document_title,
            publication_year=hit.publication_year,
            pages=pages,
            excerpt=hit.text,
            cosine_distance=distance,
            similarity=None if distance is None else round(1 - distance, 6),
            lexical_score=hit.lexical_score,
        )


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    candidate_k: int
    results: list[SearchResultOut]
    # How many searchable documents matched the filters. Zero explains an empty result.
    searched_documents: int
    embedding_model_id: str | None
    embedding_model_revision: str | None
    query_instruction: str | None
    timings_ms: dict[str, float]
    score_note: str = SCORE_NOTE


@router.post("/search")
def search(request: Request, session: SessionDep, settings: SettingsDep, body: SearchRequest) -> SearchResponse:
    """Rank passages from active, fully indexed documents. Exact search: every chunk is compared."""
    k = body.candidate_k or settings.retrieval_candidate_k
    filters = SearchFilters(
        document_ids=tuple(body.filters.document_ids),
        publication_year_from=body.filters.publication_year_from,
        publication_year_to=body.filters.publication_year_to,
    )
    embedder = query_embedder(request) if body.mode == "vector" else None
    result = retrieval.search(session, body.query, filters, k, body.mode, embedder)
    return SearchResponse(
        query=body.query,
        mode=body.mode,
        candidate_k=k,
        results=[SearchResultOut.from_hit(hit) for hit in result.hits],
        searched_documents=result.searched_documents,
        embedding_model_id=embedder.model_id if embedder else None,
        embedding_model_revision=embedder.revision if embedder else None,
        query_instruction=embedder.query_instruction if embedder else None,
        timings_ms=result.timings_ms,
    )
