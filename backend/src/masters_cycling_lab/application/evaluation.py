"""Labelled retrieval evaluation.

Questions and gold labels live in git (research/evaluation/questions.jsonl). Gold evidence is anchored to a corpus
paper, a physical page and an exact quotation, not to chunk IDs, so labels survive changes to chunking. Each run is
stored as a database row and a JSON artifact that records everything needed to reproduce or compare it.
"""

import hashlib
import json
import math
import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from masters_cycling_lab.application import retrieval
from masters_cycling_lab.application.corpus import ManifestEntry
from masters_cycling_lab.config import REPO_ROOT
from masters_cycling_lab.domain import evaluation as metrics
from masters_cycling_lab.domain.evaluation import EvidenceSpan
from masters_cycling_lab.domain.ports import Embedder
from masters_cycling_lab.domain.retrieval import SearchFilters, SearchHit, SearchMode
from masters_cycling_lab.infrastructure.db.models import (
    Document,
    DocumentPage,
    EvaluationResult,
    EvaluationRun,
    IndexVersion,
)

DEFAULT_QUESTIONS = REPO_ROOT / "research" / "evaluation" / "questions.jsonl"
CUTOFFS = (5, 10)
Grade = Literal[0, 1, 2]


class GoldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_id: str = Field(pattern=r"^mcl-\d{3}$")
    page: int = Field(ge=1)  # physical page in the PDF
    quote: str = Field(min_length=20)  # exact text from that page; whitespace may differ
    relevance: Literal[1, 2]


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: str
    date: date
    review_status: Literal["provisional", "reviewed"]
    rationale: str


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^q\d{3}$")
    split: Literal["dev", "test"]
    question: str = Field(min_length=5, max_length=500)
    question_type: Literal["direct", "synthesis", "population_mismatch", "insufficient_evidence", "out_of_scope"]
    answerability: Literal["answerable", "partially_answerable", "insufficient_evidence", "out_of_scope"]
    population_applicability: str
    expected_points: list[str]
    expected_limitations: list[str]
    # 2 = directly answers, 1 = related or partial, 0 = judged and not relevant. Unlisted = not judged.
    document_relevance: dict[str, Grade]
    evidence: list[GoldEvidence]
    annotation: Annotation

    @model_validator(mode="after")
    def consistent(self) -> Self:
        for item in self.evidence:
            if self.document_relevance.get(item.corpus_id, 0) < 1:
                raise ValueError(f"evidence from {item.corpus_id} needs a document_relevance of 1 or 2")
        if self.answerability in ("answerable", "partially_answerable") and not self.evidence:
            raise ValueError("an answerable question needs gold evidence")
        return self


class LabelError(Exception):
    pass


def load_questions(path: Path) -> list[Question]:
    questions, problems = [], []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if line.strip():
            try:
                questions.append(Question.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as exc:
                problems.append(f"line {number}: {exc}")
    ids = [question.id for question in questions]
    problems += [f"duplicate id {qid}" for qid in sorted({qid for qid in ids if ids.count(qid) > 1})]
    if problems:
        raise LabelError("\n".join(problems))
    return questions


@dataclass
class CorpusIndex:
    """Maps between corpus IDs from the manifest and documents in the database."""

    corpus_ids: dict[uuid.UUID, str]  # document id -> corpus id
    active_versions: dict[str, uuid.UUID]  # corpus id -> active index version


def corpus_index(session: Session, entries: list[ManifestEntry]) -> CorpusIndex:
    by_sha = {entry.sha256: entry.corpus_id for entry in entries}
    rows = session.execute(
        select(Document.id, Document.sha256, Document.active_index_version_id).where(
            Document.sha256.in_(by_sha), Document.deleted_at.is_(None)
        )
    )
    corpus_ids, active = {}, {}
    for document_id, sha256, version_id in rows:
        corpus_ids[document_id] = by_sha[sha256]
        if version_id is not None:
            active[by_sha[sha256]] = version_id
    return CorpusIndex(corpus_ids, active)


def locate_evidence(
    session: Session, questions: list[Question], index: CorpusIndex
) -> tuple[dict[str, list[EvidenceSpan]], list[str]]:
    """Find every gold quotation on its stated page of the stored text. Returns spans by question and problems."""
    located: dict[str, list[EvidenceSpan]] = {}
    problems = []
    for question in questions:
        spans = []
        for item in question.evidence:
            version = index.active_versions.get(item.corpus_id)
            if version is None:
                problems.append(f"{question.id}: {item.corpus_id} is not ingested (run make corpus-ingest)")
                continue
            page_text = session.scalar(
                select(DocumentPage.text).where(
                    DocumentPage.index_version_id == version, DocumentPage.page_number == item.page
                )
            )
            found = metrics.find_quote(page_text or "", item.quote)
            if found is None:
                problems.append(
                    f"{question.id}: quote not found on {item.corpus_id} page {item.page}: {item.quote[:60]!r}"
                )
                continue
            spans.append(EvidenceSpan(item.corpus_id, item.page, *found))
        located[question.id] = spans
    return located, problems


def score_question(
    question: Question, hits: list[SearchHit], gold: list[EvidenceSpan], index: CorpusIndex
) -> dict[str, Any]:
    scores: dict[str, Any] = {}
    relevant = {doc for doc, grade in question.document_relevance.items() if grade >= 1}
    for k in CUTOFFS:
        top = hits[:k]
        ranked = metrics.documents_in_order([index.corpus_ids.get(h.document_id, str(h.document_id)) for h in top])
        retrieved_spans = [
            EvidenceSpan(index.corpus_ids.get(h.document_id, str(h.document_id)), s.page_number, s.start, s.end)
            for h in top
            for s in h.spans
        ]
        scores[f"recall@{k}"] = metrics.recall(ranked, relevant)
        scores[f"mrr@{k}"] = metrics.reciprocal_rank(ranked, relevant)
        scores[f"ndcg@{k}"] = metrics.ndcg(ranked, dict(question.document_relevance), k)
        scores[f"evidence_coverage@{k}"] = metrics.span_coverage(retrieved_spans, gold)
        scores[f"unjudged@{k}"] = metrics.unjudged(ranked, set(question.document_relevance))
    return scores


def summarize(per_question: list[dict[str, Any]], latencies: list[float]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in per_question[0] if per_question else []:
        values = [scores[name] for scores in per_question if scores[name] is not None]
        summary[name] = round(statistics.mean(values), 4) if values else None
        summary[f"{name}_questions"] = len(values)
    if latencies:
        summary["latency_ms_mean"] = round(statistics.mean(latencies), 1)
        # Nearest-rank percentile: the smallest value at or above 95% of the measurements.
        summary["latency_ms_p95"] = round(sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1], 1)
    return summary


def run_evaluation(
    session: Session,
    embedder: Embedder,
    questions: list[Question],
    entries: list[ManifestEntry],
    *,
    split: str,
    modes: tuple[SearchMode, ...],
    k: int,
    dataset_sha256: str,
    corpus_sha256: str,
    code_revision: str | None,
    artifacts_dir: Path,
) -> tuple[uuid.UUID, Path, dict[str, Any]]:
    index = corpus_index(session, entries)
    chosen = [question for question in questions if question.split == split]
    gold, problems = locate_evidence(session, chosen, index)
    if problems:
        raise LabelError("\n".join(problems))

    started = datetime.now(UTC)
    config = run_config(session, embedder, modes, k, index)
    # The first query pays one-off model warm-up costs; latency is measured with the model already warm.
    embedder.embed_query("warm up")
    outputs: dict[str, dict[str, Any]] = {question.id: {"question": question.question} for question in chosen}
    summary: dict[str, Any] = {}
    for mode in modes:
        scored, latencies = [], []
        for question in chosen:
            result = retrieval.search(session, question.question, SearchFilters(), k, mode, embedder)
            output: dict[str, Any] = {"hits": [hit_record(hit, index) for hit in result.hits]}
            latencies.append(sum(result.timings_ms.values()))
            if question.answerability in ("answerable", "partially_answerable"):
                output["metrics"] = score_question(question, result.hits, gold[question.id], index)
                scored.append(output["metrics"])
            outputs[question.id][mode] = output
        summary[mode] = summarize(scored, latencies)

    run = EvaluationRun(
        split=split,
        status="completed",
        dataset_sha256=dataset_sha256,
        corpus_sha256=corpus_sha256,
        config=config,
        code_revision=code_revision,
        metrics=summary,
        started_at=started,
        finished_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    for question_id, output in outputs.items():
        session.add(EvaluationResult(evaluation_run_id=run.id, question_id=question_id, retrieval=output, metrics={
            mode: output[mode].get("metrics", {}) for mode in modes
        }))  # fmt: skip
    session.commit()

    artifact = {
        "evaluation_run_id": str(run.id),
        "split": split,
        "started_at": started.isoformat(),
        "dataset_sha256": dataset_sha256,
        "corpus_sha256": corpus_sha256,
        "code_revision": code_revision,
        "prompt_version": None,  # retrieval only; no prompt is involved yet
        "config": config,
        "metrics": summary,
        "questions": outputs,
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / f"{started:%Y%m%dT%H%M%SZ}-{split}-{str(run.id)[:8]}.json"
    path.write_text(json.dumps(artifact, indent=2) + "\n")
    return run.id, path, summary


def run_config(
    session: Session, embedder: Embedder, modes: tuple[SearchMode, ...], k: int, index: CorpusIndex
) -> dict[str, Any]:
    versions = session.scalars(select(IndexVersion).where(IndexVersion.id.in_(index.active_versions.values())))
    pipelines = sorted({json.dumps({"extractor": f"{v.extractor} {v.extractor_version}", "chunking": v.chunking_config},
                                   sort_keys=True) for v in versions})  # fmt: skip
    return {
        "modes": list(modes),
        "candidate_k": k,
        "cutoffs": list(CUTOFFS),
        "embedding_model_id": embedder.model_id,
        "embedding_model_revision": embedder.revision,
        "query_instruction": embedder.query_instruction,
        "lexical": "PostgreSQL to_tsquery('english', words joined with OR), ranked by ts_rank_cd",
        "index_pipelines": [json.loads(pipeline) for pipeline in pipelines],
        "searchable_corpus_documents": len(index.active_versions),
    }


def hit_record(hit: SearchHit, index: CorpusIndex) -> dict[str, Any]:
    return {
        "rank": hit.rank,
        "corpus_id": index.corpus_ids.get(hit.document_id),
        "chunk_id": str(hit.chunk_id),
        "pages": [span.page_number for span in hit.spans],
        "cosine_distance": hit.cosine_distance,
        "lexical_score": hit.lexical_score,
        "excerpt": hit.text[:300],
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
