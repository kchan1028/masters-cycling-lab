"""Experiment, 2026-11-13: could search distance tell answerable questions from unanswerable ones, and does the
evidence the app sends to the model contain the gold passage?

For every question of a split it runs the answer flow's own search and passage choice (vector search, the top
RETRIEVAL_CANDIDATE_K passages, at most RETRIEVAL_CONTEXT_K sent) without calling the model, and records the best
cosine distance and whether a sent passage overlaps a gold quotation. Read-only. Results are in docs/evaluation.md.

    uv --directory backend run python ../research/evaluation/experiments/abstention.py [dev|test|test2]
"""

import statistics
import sys

from sqlalchemy.orm import Session

from masters_cycling_lab.application import corpus, evaluation, retrieval
from masters_cycling_lab.config import get_settings
from masters_cycling_lab.domain.answers import choose_evidence
from masters_cycling_lab.domain.evaluation import EvidenceSpan
from masters_cycling_lab.domain.retrieval import SearchFilters
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import SentenceTransformerEmbedder

NO_ANSWER = ("insufficient_evidence", "out_of_scope")


def main() -> None:
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    settings = get_settings()
    questions = [q for q in evaluation.load_questions(evaluation.DEFAULT_QUESTIONS) if q.split == split]
    entries = corpus.load_manifest(corpus.DEFAULT_MANIFEST)
    embedder = SentenceTransformerEmbedder(settings)
    rows = []
    with Session(make_engine(settings.database_url)) as session:
        index = evaluation.corpus_index(session, entries)
        answerable = [q for q in questions if q.answerability not in NO_ANSWER]
        gold, problems = evaluation.locate_evidence(session, answerable, index)
        if problems:
            raise SystemExit("\n".join(problems))
        for q in questions:
            hits = retrieval.search(
                session, q.question, SearchFilters(), settings.retrieval_candidate_k, "vector", embedder
            ).hits
            # A budget large enough that only the passage limit and overlaps decide, as with the real context window.
            sent = [c.hit for c in choose_evidence(hits, settings.retrieval_context_k, 10**6) if c.label]
            spans = [
                EvidenceSpan(index.corpus_ids[h.document_id], s.page_number, s.start, s.end)
                for h in sent
                for s in h.spans
            ]
            found = [any(span.overlaps(g) for span in spans) for g in gold.get(q.id, [])]
            rows.append((q, hits[0].cosine_distance if hits else None, found))

    print(f"{split} split, {len(questions)} questions\n")
    for label, group in (
        ("answerable", [r for r in rows if r[0].answerability not in NO_ANSWER]),
        ("no evidence / out of scope", [r for r in rows if r[0].answerability in NO_ANSWER]),
    ):
        best = sorted(d for _, d, _ in group if d is not None)
        print(f"{label} ({len(group)}): best distance min {best[0]:.3f}, median {statistics.median(best):.3f}, "
              f"max {best[-1]:.3f}")  # fmt: skip
    print("\nPer question (best distance, gold passages sent / gold passages):")
    for q, distance, found in sorted(rows, key=lambda row: row[1] or 0):
        mark = "NO-ANSWER" if q.answerability in NO_ANSWER else f"{sum(found)}/{len(found)} gold sent"
        print(f"  {distance:.3f}  {q.id}  {mark:14}  {q.question[:70]}")
    answerable_rows = [r for r in rows if r[0].answerability not in NO_ANSWER]
    with_gold = sum(any(found) for _, _, found in answerable_rows)
    print(f"\nAnswerable questions with a gold passage sent to the model: {with_gold}/{len(answerable_rows)}")


if __name__ == "__main__":
    main()
