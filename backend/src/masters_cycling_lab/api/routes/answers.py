import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from masters_cycling_lab.api.dependencies import SessionDep, SettingsDep, language_model, query_embedder
from masters_cycling_lab.api.routes.retrieval import FiltersIn
from masters_cycling_lab.application import answering
from masters_cycling_lab.application.answering import AnswerView
from masters_cycling_lab.domain.retrieval import SearchFilters

router = APIRouter(prefix="/answers", tags=["answers"])


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=1000)
    filters: FiltersIn = Field(default_factory=FiltersIn)
    include_debug: bool = False


class CitationOut(BaseModel):
    evidence_id: str  # E1, E2... as used in the answer text
    document_id: uuid.UUID
    document_title: str | None
    authors: list[str]
    publication_year: int | None
    doi: str | None
    # How far the bibliographic data can be trusted (manifest_verified, user_supplied, extracted_unverified).
    metadata_source: str | None
    page_numbers: list[int]  # physical PDF pages
    page_labels: list[str | None]
    excerpt: str  # exactly the passage the model was shown, from the stored snapshot
    chunk_id: uuid.UUID | None
    index_version_id: uuid.UUID | None
    file_url: str | None  # None once the document has been deleted


class ClaimOut(BaseModel):
    text: str
    citations: list[CitationOut]


class CandidateOut(BaseModel):
    rank: int
    evidence_id: str | None
    selected: bool
    reason: str | None
    document_id: uuid.UUID
    document_title: str | None
    page_numbers: list[int]
    cosine_distance: float
    similarity: float
    excerpt: str


class AnswerDebugOut(BaseModel):
    query_run_id: uuid.UUID
    retrieval_config: dict[str, Any]
    generation_config: dict[str, Any] | None
    embedding_model_id: str
    embedding_model_revision: str
    llm_model: str | None
    prompt_version: str | None
    timings_ms: dict[str, Any]
    usage: dict[str, Any] | None
    candidates: list[CandidateOut]


class AnswerOut(BaseModel):
    query_run_id: uuid.UUID
    question: str
    status: Literal["running", "answered", "insufficient_evidence", "failed"]
    answer_text: str | None
    claims: list[ClaimOut]
    limitations: list[str]
    error_code: str | None
    embedding_model_id: str
    llm_model: str | None
    prompt_version: str | None
    timings_ms: dict[str, Any]
    created_at: datetime
    debug: AnswerDebugOut | None = None
    note: str = "Citations show what each claim was based on. They do not prove the passage fully supports the claim."


def citation_out(view: answering.CitationView) -> CitationOut:
    row, meta = view.evidence, view.evidence.source_metadata
    first_page = row.page_numbers[0] if row.page_numbers else 1
    return CitationOut(
        evidence_id=view.label,
        document_id=row.document_id,
        document_title=meta.get("title"),
        authors=meta.get("authors") or [],
        publication_year=meta.get("publication_year"),
        doi=meta.get("doi"),
        metadata_source=meta.get("metadata_source"),
        page_numbers=row.page_numbers,
        page_labels=meta.get("page_labels") or [],
        excerpt=row.passage_text,
        chunk_id=row.chunk_id,
        index_version_id=row.index_version_id,
        file_url=f"/api/v1/documents/{row.document_id}/file#page={first_page}" if view.document_exists else None,
    )


def debug_out(view: AnswerView) -> AnswerDebugOut:
    run = view.run
    return AnswerDebugOut(
        query_run_id=run.id,
        retrieval_config=run.retrieval_config,
        generation_config=run.generation_config,
        embedding_model_id=run.embedding_model_id,
        embedding_model_revision=run.embedding_model_revision,
        llm_model=run.llm_model,
        prompt_version=run.prompt_version,
        timings_ms=run.timings,
        usage=run.usage,
        candidates=[
            CandidateOut(
                rank=row.retrieval_rank,
                evidence_id=row.evidence_label,
                selected=row.selected_for_context,
                reason=row.selection_reason,
                document_id=row.document_id,
                document_title=row.source_metadata.get("title"),
                page_numbers=row.page_numbers,
                cosine_distance=row.cosine_distance,
                similarity=round(1 - row.cosine_distance, 6),
                excerpt=row.passage_text,
            )
            for row in view.candidates
        ],
    )


def answer_out(view: AnswerView, include_debug: bool) -> AnswerOut:
    run = view.run
    return AnswerOut(
        query_run_id=run.id,
        question=run.question,
        status=run.status,
        answer_text=run.answer_text,
        claims=[
            ClaimOut(text=claim.text, citations=[citation_out(c) for c in citations])
            for claim, citations in view.claims
        ],
        limitations=run.limitations,
        error_code=run.error_code,
        embedding_model_id=run.embedding_model_id,
        llm_model=run.llm_model,
        prompt_version=run.prompt_version,
        timings_ms=run.timings,
        created_at=run.created_at,
        debug=debug_out(view) if include_debug else None,
    )


@router.post("", responses={502: {"description": "The model's reply failed validation twice"},
                            503: {"description": "Generation not configured or the provider failed"}})  # fmt: skip
def ask(request: Request, session: SessionDep, settings: SettingsDep, body: AnswerRequest) -> AnswerOut:
    """Answer from the indexed research. Abstains without calling the model when nothing relevant is found."""
    filters = SearchFilters(
        document_ids=tuple(body.filters.document_ids),
        publication_year_from=body.filters.publication_year_from,
        publication_year_to=body.filters.publication_year_to,
    )
    run_id = answering.answer_question(
        session, query_embedder(request), language_model(request), settings, body.question, filters
    )
    return answer_out(answering.get_answer(session, run_id), body.include_debug)


@router.get("/{query_run_id}")
def get_answer(session: SessionDep, query_run_id: uuid.UUID) -> AnswerOut:
    return answer_out(answering.get_answer(session, query_run_id), include_debug=False)


@router.get("/{query_run_id}/debug")
def get_answer_debug(session: SessionDep, query_run_id: uuid.UUID) -> AnswerDebugOut:
    """Every retrieved candidate, whether it was sent and why, budgets, models and timings. No raw prompt."""
    return debug_out(answering.get_answer(session, query_run_id))
