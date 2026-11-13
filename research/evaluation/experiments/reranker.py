"""Dev-split experiment, 2026-11-12: re-score the top vector passages with a cross-encoder reranker.

The weakness found so far is choosing the right passage within the right paper. A cross-encoder reads the question
and each passage together, which a single embedding per passage cannot. This takes the top N vector passages,
re-scores them, keeps the best 10 and scores them with the project's own metrics (the helpers are shared with
retrieval_levers.py). Read-only. Results are in docs/evaluation.md ("Experiments").

    uv --directory backend run python ../research/evaluation/experiments/reranker.py

The first run downloads the rerankers below into MODEL_CACHE_DIR (data/models, git-ignored). Dev questions only.
"""

import statistics
import time

from retrieval_levers import passages, report, scores
from sentence_transformers import CrossEncoder
from sqlalchemy.orm import Session

from masters_cycling_lab.application import corpus, evaluation, retrieval
from masters_cycling_lab.config import get_settings
from masters_cycling_lab.domain.retrieval import SearchFilters, SearchHit
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import SentenceTransformerEmbedder

# Pinned to the revisions the reported results were measured with. The MiniLM models (Apache-2.0, about 90 and
# 130 MB) were trained on MS MARCO web search; bge-reranker-base (MIT, about 1.1 GB) on broader data.
RERANKERS = [
    ("cross-encoder/ms-marco-MiniLM-L-6-v2", "233902d25c440f23af6f7d6e94d2946bac0bee0a"),
    ("cross-encoder/ms-marco-MiniLM-L-12-v2", "7b0235231ca2674cb8ca8f022859a6eba2b1c968"),
    ("BAAI/bge-reranker-base", "2cfc18c9415c912f9d8155881c133215df768a70"),
]
DEPTHS = [20, 50]  # how many vector passages are re-scored


def reranked(model: CrossEncoder, question: str, hits: list[SearchHit]) -> list[SearchHit]:
    relevance = model.predict([(question, hit.text) for hit in hits], show_progress_bar=False)
    order = sorted(range(len(hits)), key=lambda i: -float(relevance[i]))  # stable: ties keep the vector order
    return [hits[i] for i in order]


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
        pool = {
            q.id: retrieval.search(session, q.question, SearchFilters(), max(DEPTHS), "vector", embedder).hits
            for q in scored
        }

    print(f"Dev split, {len(scored)} scored questions, top 10 passages\n")
    report("vector only", [scores(q, passages(pool[q.id], index.corpus_ids), gold[q.id], 10) for q in scored])
    for name, revision in RERANKERS:
        model = CrossEncoder(name, revision=revision, max_length=512, cache_folder=str(settings.model_cache_dir))
        model.predict([("warm up", "warm up")], show_progress_bar=False)
        print(f"\n{name} at {revision}")
        for depth in DEPTHS:
            per_question, seconds = [], []
            for q in scored:
                started = time.perf_counter()
                hits = reranked(model, q.question, pool[q.id][:depth])
                seconds.append(time.perf_counter() - started)
                per_question.append(scores(q, passages(hits, index.corpus_ids), gold[q.id], 10))
            median_ms = statistics.median(seconds) * 1000
            report(f"rerank top {depth}", per_question, f"  median {median_ms:.0f} ms per question")


if __name__ == "__main__":
    main()
