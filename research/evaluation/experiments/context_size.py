"""Experiment, 2026-11-13: how many passages should go to the model?

For each answerable question, does a gold passage reach the model when the app sends 6, 8, 10 or 12 passages, with
the current overlap rule and without it? Read-only; no model is called. Results and the decision
(RETRIEVAL_CONTEXT_K 6 -> 10) are in docs/evaluation.md.

    uv --directory backend run python ../research/evaluation/experiments/context_size.py [dev|test2]

A held-out split runs only the two settings compared there: 6 and 10 passages with the current overlap rule.
"""

import statistics
import sys

from sqlalchemy.orm import Session

from masters_cycling_lab.application import corpus, evaluation, retrieval
from masters_cycling_lab.config import get_settings
from masters_cycling_lab.domain.answers import choose_evidence, estimate_tokens
from masters_cycling_lab.domain.evaluation import EvidenceSpan
from masters_cycling_lab.domain.retrieval import SearchFilters, SearchHit
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import SentenceTransformerEmbedder

NO_ANSWER = ("insufficient_evidence", "out_of_scope")


def sent(hits: list[SearchHit], k: int, overlap_rule: bool) -> list[SearchHit]:
    if not overlap_rule:
        return hits[:k]
    # A budget large enough that only the passage limit and the overlap rule decide.
    return [choice.hit for choice in choose_evidence(hits, k, 10**6) if choice.label]


def main() -> None:
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    settings = get_settings()
    questions = [
        q
        for q in evaluation.load_questions(evaluation.DEFAULT_QUESTIONS)
        if q.split == split and q.answerability not in NO_ANSWER
    ]
    entries = corpus.load_manifest(corpus.DEFAULT_MANIFEST)
    embedder = SentenceTransformerEmbedder(settings)
    with Session(make_engine(settings.database_url)) as session:
        index = evaluation.corpus_index(session, entries)
        gold, problems = evaluation.locate_evidence(session, questions, index)
        if problems:
            raise SystemExit("\n".join(problems))
        pools = {
            q.id: retrieval.search(session, q.question, SearchFilters(), 30, "vector", embedder).hits for q in questions
        }

    variants = [(6, True), (8, True), (10, True), (12, True), (6, False), (8, False), (10, False), (12, False)]
    if split != "dev":
        variants = [(6, True), (10, True)]
    print(f"{split}: {len(questions)} answerable questions")
    for k, overlap_rule in variants:
        with_gold = covered = total = 0
        tokens = []
        for q in questions:
            hits = sent(pools[q.id], k, overlap_rule)
            spans = [
                EvidenceSpan(index.corpus_ids[h.document_id], s.page_number, s.start, s.end)
                for h in hits
                for s in h.spans
            ]
            found = [any(span.overlaps(g) for span in spans) for g in gold[q.id]]
            with_gold += any(found)
            covered += sum(found)
            total += len(found)
            tokens.append(sum(estimate_tokens(h.text) + 40 for h in hits))
        rule = "overlap rule" if overlap_rule else "no overlap rule"
        print(
            f"  {k:2} passages, {rule:15}: {with_gold}/{len(questions)} questions with a gold passage sent, "
            f"{covered}/{total} gold passages, median ~{statistics.median(tokens):.0f} tokens"
        )


if __name__ == "__main__":
    main()
