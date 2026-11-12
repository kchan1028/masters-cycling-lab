"""Dev-split experiment, 2026-11-12: three ways to improve retrieval, measured before changing any code.

1. A cap on passages per paper in the top 10.
2. Smaller chunks, at 10 passages and at an equal token budget.
3. Reciprocal rank fusion of the vector and lexical rankings.

Read-only: it re-chunks the stored page text in memory with the project's chunker, embeds with the pinned model and
ranks by exact cosine similarity; nothing in the database changes. Results and conclusions are in
docs/evaluation.md ("Experiments"). Run with the stack up and the corpus ingested:

    uv --directory backend run python ../research/evaluation/experiments/retrieval_levers.py

Takes about 3 minutes on a laptop CPU. Dev questions only: the test split is not used for choosing settings.
"""

import statistics
import uuid
from collections import Counter

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from masters_cycling_lab.application import corpus, evaluation, retrieval
from masters_cycling_lab.config import get_settings
from masters_cycling_lab.domain import evaluation as metrics
from masters_cycling_lab.domain.chunking import ChunkingConfig, chunk_pages
from masters_cycling_lab.domain.evaluation import EvidenceSpan
from masters_cycling_lab.domain.extraction import ExtractedPage
from masters_cycling_lab.domain.retrieval import SearchFilters, SearchHit
from masters_cycling_lab.infrastructure.db.models import DocumentPage
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import SentenceTransformerEmbedder

CAPS = [None, 3, 2, 1]
CHUNKINGS = [(300, 40), (200, 30), (150, 30), (100, 20)]
TOKEN_BUDGET = 3000  # 10 passages of the current 300-token chunks
RRF_K = 60  # the usual constant for reciprocal rank fusion

Passage = tuple[str, int, int, int]  # corpus ID, physical page, start, end


def scores(question: evaluation.Question, ranked: list[Passage], gold: list[EvidenceSpan], k: int) -> dict:
    """The same definitions as evaluation.score_question, at any k."""
    top = ranked[:k]
    relevant = {doc for doc, grade in question.document_relevance.items() if grade >= 1}
    documents = metrics.documents_in_order([passage[0] for passage in top])
    return {
        "recall": metrics.recall(documents, relevant),
        "mrr": metrics.reciprocal_rank(documents, relevant),
        "ndcg": metrics.ndcg(documents, dict(question.document_relevance), 10),
        "evidence": metrics.span_coverage([EvidenceSpan(*passage) for passage in top], gold),
    }


def report(label: str, per_question: list[dict], extra: str = "") -> None:
    means = {key: statistics.mean(s[key] for s in per_question if s[key] is not None) for key in per_question[0]}
    print(f"  {label:40} " + "  ".join(f"{key} {value:.2f}" for key, value in means.items()) + extra)


def passages(hits: list[SearchHit], corpus_ids: dict[uuid.UUID, str]) -> list[Passage]:
    return [(corpus_ids[hit.document_id], span.page_number, span.start, span.end) for hit in hits for span in hit.spans]


def capped(hits: list[SearchHit], cap: int | None) -> list[SearchHit]:
    if cap is None:
        return hits
    seen: Counter[uuid.UUID] = Counter()
    kept = []
    for hit in hits:
        if seen[hit.document_id] < cap:
            seen[hit.document_id] += 1
            kept.append(hit)
    return kept


def fused(vector: list[SearchHit], lexical: list[SearchHit], lexical_weight: float) -> list[SearchHit]:
    score: dict[uuid.UUID, float] = {}
    by_chunk: dict[uuid.UUID, SearchHit] = {}
    for weight, hits in ((1.0, vector), (lexical_weight, lexical)):
        for rank, hit in enumerate(hits, start=1):
            score[hit.chunk_id] = score.get(hit.chunk_id, 0.0) + weight / (RRF_K + rank)
            by_chunk[hit.chunk_id] = hit
    return [by_chunk[chunk_id] for chunk_id in sorted(score, key=lambda chunk_id: -score[chunk_id])]


def main() -> None:
    settings = get_settings()
    questions = [q for q in evaluation.load_questions(evaluation.DEFAULT_QUESTIONS) if q.split == "dev"]
    scored = [q for q in questions if q.answerability in ("answerable", "partially_answerable")]
    entries = corpus.load_manifest(corpus.DEFAULT_MANIFEST)
    embedder = SentenceTransformerEmbedder(settings)

    with Session(make_engine(settings.database_url)) as session:
        index = evaluation.corpus_index(session, entries)
        gold, problems = evaluation.locate_evidence(session, scored, index)
        if problems:
            raise SystemExit("\n".join(problems))
        print(f"Dev split, {len(scored)} scored questions\n")

        vector = {
            q.id: retrieval.search(session, q.question, SearchFilters(), 100, "vector", embedder).hits for q in scored
        }
        lexical = {q.id: retrieval.search(session, q.question, SearchFilters(), 100, "lexical").hits for q in scored}

        print("1. Passages per paper in the top 10 (current index, vector search)")
        for cap in CAPS:
            top = {q.id: capped(vector[q.id], cap) for q in scored}
            papers = statistics.mean(len({hit.document_id for hit in top[q.id][:10]}) for q in scored)
            per_question = [scores(q, passages(top[q.id], index.corpus_ids), gold[q.id], 10) for q in scored]
            report("no cap" if cap is None else f"at most {cap} per paper", per_question, f"  papers {papers:.1f}")

        print("\n2. Chunk size (stored page text re-chunked in memory, vector search)")
        version_to_corpus = {version: corpus_id for corpus_id, version in index.active_versions.items()}
        pages: dict[str, list[ExtractedPage]] = {}
        rows = session.execute(
            select(DocumentPage.index_version_id, DocumentPage.page_number, DocumentPage.text).where(
                DocumentPage.index_version_id.in_(list(index.active_versions.values()))
            )
        )
        for version, page_number, text in rows:
            pages.setdefault(version_to_corpus[version], []).append(ExtractedPage(page_number, None, text))
        queries = {q.id: embedder.embed_query(q.question) for q in scored}
        for max_tokens, overlap in CHUNKINGS:
            config = ChunkingConfig(max_tokens=max_tokens, overlap_tokens=overlap)
            chunks: list[Passage] = []
            texts: list[str] = []
            for corpus_id in sorted(pages):  # paper, then position: the same tie order as the search code
                for draft in chunk_pages(
                    sorted(pages[corpus_id], key=lambda p: p.page_number), embedder.token_offsets, config
                ):
                    span = draft.spans[0]
                    chunks.append((corpus_id, span.page_number, span.start, span.end))
                    texts.append(draft.text)
            vectors = embedder.embed_documents(texts)
            budget_k = TOKEN_BUDGET // max_tokens
            ranked = {
                q.id: [chunks[i] for i in np.argsort(-(vectors @ queries[q.id]), kind="stable")[:30]] for q in scored
            }
            print(f"  {max_tokens} tokens, {overlap} overlap: {len(chunks)} chunks")
            report("    top 10 passages", [scores(q, ranked[q.id], gold[q.id], 10) for q in scored])
            report(
                f"    top {budget_k} passages (~{TOKEN_BUDGET} tokens)",
                [scores(q, ranked[q.id], gold[q.id], budget_k) for q in scored],
            )

        print("\n3. Reciprocal rank fusion of vector and lexical (current index, top 10)")
        for label, weight in (
            ("vector only", 0.0),
            ("fusion, equal weight", 1.0),
            ("fusion, lexical at half weight", 0.5),
        ):
            per_question = [
                scores(q, passages(fused(vector[q.id], lexical[q.id], weight), index.corpus_ids), gold[q.id], 10)
                for q in scored
            ]
            report(label, per_question)


if __name__ == "__main__":
    main()
