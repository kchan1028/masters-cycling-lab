"""Dev-split experiment, 2026-11-14: rank the stored 300-token passages by their best-matching small window.

The weakness found so far is choosing the right passage within the right paper: one embedding per 300-token passage
blurs a single finding into everything else on that part of the page. Smaller chunks found more papers but returned
less text. This keeps the passages the model sees (the same 300-token chunks, so the same ~3,000-token context at 10)
and changes only how they are ranked: every passage is split into small windows, each window is embedded, and a
passage is scored by

    alpha * similarity(passage) + (1 - alpha) * max similarity(window inside the passage)

alpha = 1 is plain vector search and reproduces the official run. A window belongs to every passage that holds its
midpoint (passages overlap by 40 tokens). Read-only: everything is rebuilt in memory from the stored page text with
the project's chunker and the pinned model; nothing in the database changes. Results are in docs/evaluation.md
("Experiments"). Run with the stack up and the corpus ingested:

    uv --directory backend run python ../research/evaluation/experiments/small_to_big.py

Choose settings on the dev split (the default). A held-out split is for one check of the configuration already
chosen, from a commit:

    ... small_to_big.py --split test2 --windows 60:15 --alphas 1 0.5
"""

import argparse
import statistics
from bisect import bisect_right

import numpy as np
from retrieval_levers import Passage, report, scores
from sqlalchemy import select
from sqlalchemy.orm import Session

from masters_cycling_lab.application import corpus, evaluation
from masters_cycling_lab.config import get_settings
from masters_cycling_lab.domain.chunking import ChunkingConfig, chunk_pages
from masters_cycling_lab.domain.extraction import ExtractedPage
from masters_cycling_lab.infrastructure.db.models import DocumentPage
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import SentenceTransformerEmbedder

PASSAGE = ChunkingConfig(max_tokens=300, overlap_tokens=40)  # the stored index
WINDOWS = ["100:20", "60:15", "40:10"]  # max_tokens:overlap_tokens of the small windows
ALPHAS = [1.0, 0.75, 0.5, 0.25, 0.0]
K = 10


def load_pages(session: Session, index: evaluation.CorpusIndex) -> dict[str, list[ExtractedPage]]:
    version_to_corpus = {version: corpus_id for corpus_id, version in index.active_versions.items()}
    pages: dict[str, list[ExtractedPage]] = {}
    rows = session.execute(
        select(DocumentPage.index_version_id, DocumentPage.page_number, DocumentPage.text).where(
            DocumentPage.index_version_id.in_(list(index.active_versions.values()))
        )
    )
    for version, page_number, text in rows:
        pages.setdefault(version_to_corpus[version], []).append(ExtractedPage(page_number, None, text))
    return {corpus_id: sorted(found, key=lambda p: p.page_number) for corpus_id, found in pages.items()}


def chunked(
    pages: dict[str, list[ExtractedPage]], embedder: SentenceTransformerEmbedder, config: ChunkingConfig
) -> tuple[list[Passage], list[str]]:
    """Paper, then position: the same tie order as the search code."""
    spans: list[Passage] = []
    texts: list[str] = []
    for corpus_id in sorted(pages):
        for draft in chunk_pages(pages[corpus_id], embedder.token_offsets, config):
            span = draft.spans[0]
            spans.append((corpus_id, span.page_number, span.start, span.end))
            texts.append(draft.text)
    return spans, texts


def owners(passages: list[Passage], windows: list[Passage]) -> list[list[int]]:
    """For each window, the passages that hold its midpoint."""
    by_page: dict[tuple[str, int], list[int]] = {}
    for i, (corpus_id, page, _, _) in enumerate(passages):
        by_page.setdefault((corpus_id, page), []).append(i)  # already in start order
    result = []
    for corpus_id, page, start, end in windows:
        candidates = by_page[(corpus_id, page)]
        middle = (start + end) // 2
        last = bisect_right([passages[i][2] for i in candidates], middle)
        result.append([i for i in candidates[:last] if passages[i][3] > middle])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--split", default="dev")
    parser.add_argument("--windows", nargs="+", default=WINDOWS)
    parser.add_argument("--alphas", nargs="+", type=float, default=ALPHAS)
    args = parser.parse_args()

    settings = get_settings()
    questions = [q for q in evaluation.load_questions(evaluation.DEFAULT_QUESTIONS) if q.split == args.split]
    scored = [q for q in questions if q.answerability in ("answerable", "partially_answerable")]
    entries = corpus.load_manifest(corpus.DEFAULT_MANIFEST)
    embedder = SentenceTransformerEmbedder(settings)

    with Session(make_engine(settings.database_url)) as session:
        index = evaluation.corpus_index(session, entries)
        gold, problems = evaluation.locate_evidence(session, scored, index)
        if problems:
            raise SystemExit("\n".join(problems))
        pages = load_pages(session, index)

    print(f"{args.split} split, {len(scored)} scored questions, top {K} of {PASSAGE.max_tokens}-token passages\n")
    passages, texts = chunked(pages, embedder, PASSAGE)
    passage_vectors = embedder.embed_documents(texts)
    queries = np.stack([embedder.embed_query(q.question) for q in scored])
    passage_sims = queries @ passage_vectors.T  # questions x passages

    for setting in args.windows:
        max_tokens, overlap = (int(part) for part in setting.split(":"))
        windows, window_texts = chunked(pages, embedder, ChunkingConfig(max_tokens=max_tokens, overlap_tokens=overlap))
        window_sims = queries @ embedder.embed_documents(window_texts).T
        best = np.full_like(passage_sims, -np.inf)
        for w, holders in enumerate(owners(passages, windows)):
            for p in holders:
                np.maximum(best[:, p], window_sims[:, w], out=best[:, p])
        if np.isinf(best).any():
            raise SystemExit(f"{setting}: some passages hold no window midpoint")

        print(f"Windows of {max_tokens} tokens, {overlap} overlap: {len(windows)} windows")
        for alpha in args.alphas:
            combined = alpha * passage_sims + (1 - alpha) * best
            per_question = []
            papers = []
            for row, q in enumerate(scored):
                order = np.argsort(-combined[row], kind="stable")[:K]
                ranked = [passages[i] for i in order]
                per_question.append(scores(q, ranked, gold[q.id], K))
                papers.append(len({passage[0] for passage in ranked}))
            report(f"  alpha {alpha:.2f}", per_question, f"  papers {statistics.mean(papers):.1f}")
        print()


if __name__ == "__main__":
    main()
