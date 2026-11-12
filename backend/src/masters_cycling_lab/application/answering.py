"""Answer a question from the indexed research, with citations that point at exactly what the model was shown.

Every run is stored: the question, the configuration, every retrieved candidate with why it was or wasn't sent,
a snapshot of each passage that was sent, and the validated claims with their citations. The raw prompt and the raw
model reply are not stored or exposed.
"""

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from masters_cycling_lab.application import retrieval
from masters_cycling_lab.application.errors import GenerationFailed, NotFound, ProviderUnavailable
from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.answers import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    EvidenceChoice,
    InvalidAnswer,
    choose_evidence,
    estimate_tokens,
    parse_answer,
    render_answer,
    user_message,
)
from masters_cycling_lab.domain.ports import Embedder, LanguageModel, ProviderError
from masters_cycling_lab.domain.retrieval import SearchFilters
from masters_cycling_lab.infrastructure.db.models import AnswerCitation, AnswerClaim, Document, QueryEvidence, QueryRun

NO_EVIDENCE = "No indexed passage matched this question and its filters, so no answer was generated."


def answer_question(
    session: Session,
    embedder: Embedder,
    llm: LanguageModel | None,
    settings: Settings,
    question: str,
    filters: SearchFilters,
) -> uuid.UUID:
    # Reserve room for the instructions, the question, the answer and some slack; passages get what is left.
    budget = (
        settings.llm_context_window_tokens
        - settings.llm_max_output_tokens
        - estimate_tokens(SYSTEM_PROMPT)
        - estimate_tokens(question)
        - 200
    )
    run = QueryRun(
        question=question,
        filters={
            "document_ids": [str(i) for i in filters.document_ids],
            "publication_year_from": filters.publication_year_from,
            "publication_year_to": filters.publication_year_to,
        },
        embedding_model_id=embedder.model_id,
        embedding_model_revision=embedder.revision,
        llm_model=llm.model if llm else None,
        prompt_version=PROMPT_VERSION,
        generation_config={"max_output_tokens": settings.llm_max_output_tokens, "temperature": 0} if llm else None,
    )
    session.add(run)

    result = retrieval.search(session, question, filters, settings.retrieval_candidate_k, "vector", embedder)
    choices = choose_evidence(result.hits, settings.retrieval_context_k, budget)
    chosen = [choice for choice in choices if choice.label]
    run.retrieval_config = {
        "mode": "vector",
        "candidate_k": settings.retrieval_candidate_k,
        "context_k": settings.retrieval_context_k,
        "context_token_budget": budget,
        "context_tokens_used": sum(estimate_tokens(choice.hit.text) + 40 for choice in chosen),
    }
    run.index_version_ids = sorted({hit.index_version_id for hit in result.hits})
    timings = dict(result.timings_ms)
    session.flush()
    evidence = store_evidence(session, run.id, choices)

    if not chosen:
        # Nothing to ground an answer in: abstain without calling the model.
        run.status, run.answer_text, run.timings = "insufficient_evidence", NO_EVIDENCE, timings
        session.commit()
        return run.id
    if llm is None:
        fail(session, run, "LLM_NOT_CONFIGURED", timings)
        raise ProviderUnavailable("LLM_NOT_CONFIGURED", "Answer generation is off: set LLM_BASE_URL and LLM_MODEL.")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message(question, chosen)},
    ]
    allowed = {choice.label for choice in chosen if choice.label}
    started = time.perf_counter()
    for attempt in (1, 2):  # the first reply, then at most one repair
        try:
            reply = llm.complete(messages, settings.llm_max_output_tokens)
        except ProviderError as exc:
            fail(session, run, "PROVIDER_UNAVAILABLE", timings)
            raise ProviderUnavailable("PROVIDER_UNAVAILABLE", str(exc)) from exc
        try:
            draft = parse_answer(reply.text, allowed)
            break
        except InvalidAnswer as problem:
            if attempt == 2:
                fail(session, run, "GENERATION_INVALID", timings)
                raise GenerationFailed(
                    "GENERATION_INVALID", f"The model's answer failed validation twice: {problem}"
                ) from problem
            repair = (
                f"Your reply was rejected: {problem} "
                f"Reply again with only the JSON object, citing only {', '.join(sorted(allowed))}."
            )
            messages += [{"role": "assistant", "content": reply.text}, {"role": "user", "content": repair}]

    timings["generation"] = round((time.perf_counter() - started) * 1000, 1)
    for ordinal, claim in enumerate(draft.claims):
        row = AnswerClaim(query_run_id=run.id, ordinal=ordinal, text=claim.text)
        session.add(row)
        session.flush()
        for label in claim.evidence_ids:
            session.add(AnswerCitation(query_run_id=run.id, claim_id=row.id, evidence_id=evidence[label].id))
    run.status = draft.status
    run.answer_text = render_answer(draft)
    run.limitations = list(draft.limitations)
    run.timings = timings
    run.usage = {"attempts": attempt, **reply.usage} if reply.usage else None
    session.commit()
    return run.id


def store_evidence(session: Session, run_id: uuid.UUID, choices: list[EvidenceChoice]) -> dict[str, QueryEvidence]:
    """Snapshot every candidate. The text stored for a labelled passage is exactly the text the model was shown."""
    ids = {choice.hit.document_id for choice in choices}
    documents = {doc.id: doc for doc in session.scalars(select(Document).where(Document.id.in_(ids)))}
    labelled = {}
    for choice in choices:
        hit, document = choice.hit, documents[choice.hit.document_id]
        row = QueryEvidence(
            query_run_id=run_id,
            document_id=hit.document_id,
            index_version_id=hit.index_version_id,
            chunk_id=hit.chunk_id,
            evidence_label=choice.label,
            retrieval_rank=hit.rank,
            cosine_distance=min(2.0, max(0.0, hit.cosine_distance or 0.0)),
            selected_for_context=choice.label is not None,
            selection_reason=choice.reason,
            passage_text=hit.text,
            page_numbers=[span.page_number for span in hit.spans],
            source_metadata={
                "title": document.title,
                "authors": document.authors,
                "publication_year": document.publication_year,
                "doi": document.doi,
                "metadata_source": document.metadata_source,
                "page_labels": [span.page_label for span in hit.spans],
            },
        )
        session.add(row)
        if choice.label:
            labelled[choice.label] = row
    session.flush()
    return labelled


def fail(session: Session, run: QueryRun, code: str, timings: dict[str, float]) -> None:
    run.status, run.error_code, run.timings = "failed", code, timings
    session.commit()


@dataclass
class CitationView:
    label: str
    evidence: QueryEvidence
    document_exists: bool


@dataclass
class AnswerView:
    run: QueryRun
    claims: list[tuple[AnswerClaim, list[CitationView]]] = field(default_factory=list)
    candidates: list[QueryEvidence] = field(default_factory=list)


def get_answer(session: Session, run_id: uuid.UUID) -> AnswerView:
    run = session.get(QueryRun, run_id)
    if run is None:
        raise NotFound("ANSWER_NOT_FOUND", "No answer with this ID.")
    candidates = list(
        session.scalars(
            select(QueryEvidence).where(QueryEvidence.query_run_id == run_id).order_by(QueryEvidence.retrieval_rank)
        )
    )
    by_id = {row.id: row for row in candidates}
    document_ids = {row.document_id for row in candidates}
    live = set(session.scalars(select(Document.id).where(Document.id.in_(document_ids), Document.deleted_at.is_(None))))
    view = AnswerView(run, candidates=candidates)
    claims = session.scalars(
        select(AnswerClaim).where(AnswerClaim.query_run_id == run_id).order_by(AnswerClaim.ordinal)
    )
    for claim in claims:
        evidence_ids = session.scalars(select(AnswerCitation.evidence_id).where(AnswerCitation.claim_id == claim.id))
        citations = [
            CitationView(
                by_id[evidence_id].evidence_label or "", by_id[evidence_id], by_id[evidence_id].document_id in live
            )
            for evidence_id in evidence_ids
        ]
        view.claims.append((claim, sorted(citations, key=lambda citation: int(citation.label[1:]))))
    return view
