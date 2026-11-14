# 0006: How retrieval changes are evaluated and adopted

Date: 2026-11-14. Status: accepted. Label: **Current Design**.

The method below is how the project has worked since the first evaluation run on 2026-11-12. It is recorded in
[evaluation.md](../evaluation.md) and the code; this record collects it in one place.

## Context

Retrieval quality is the main weakness: passage-level evidence coverage is 0.45 on dev and 0.41 on the held-out
`test2` split, against a 0.60 target. Several cheap levers looked promising on dev questions. With 37 scored dev and
18 scored `test2` questions, one question moves an average by about 3 and 6 points, so it is easy to fool yourself.

## Requirements and constraints

- Every reported number must be reproducible: tied to a commit, a questions file and the index settings.
- Tuning must not leak into the numbers used to report.
- The method has to work for one person with no budget for a large labelled set.
- Answer quality is a separate question from retrieval quality and must not be inferred from it.

## Alternatives considered

| Option | Why not |
|---|---|
| Judge changes by reading a few answers | Not repeatable, and biased towards the examples that prompted the change |
| An LLM as judge for relevance or support | Cheap at scale, but it measures model judgment. The project keeps human review as the reference and labels any automated judgment as such |
| A public benchmark (for example BEIR or MS MARCO) | Different domain. Two rerankers trained on MS MARCO web search gave no gain on this corpus of physiology papers |
| A labelled in-domain set with dev and held-out splits (chosen) | Small, but it measures the real corpus, and held-out splits catch dev overfitting |

## Decision

- **Labelled questions in git** (`research/evaluation/questions.jsonl`): 74 questions with graded relevant papers and
  exact gold quotations by page, all reviewed by a person (dataset v5). `make labels-check` fails if any quotation is
  not on its stated page.
- **Splits.** Tune only on `dev`. `test2` is the fresh held-out split; `test` has been reported three times and is no
  longer treated as fresh. Held-out splits run only from a clean checkout.
- **Targets before results.** Targets were set on 2026-11-12 before the first run and are not lowered to make a run
  pass. Engineering gates are separate: labels resolve, runs are deterministic, p95 latency under 500 ms.
- **Every run stored.** `make evaluate` writes an `evaluation_runs` row and a JSON artifact with the git commit
  (`-dirty` if uncommitted), file hashes, model revision, chunking and extractor settings. Reported artifacts are
  committed in `research/evaluation/results/`.
- **Three modes every time.** Vector, the lexical baseline and hybrid rank fusion run side by side, and results are
  kept even when the vector approach loses.
- **Adopt only what holds out.** A change reaches the answer path only if its gain holds on a held-out split, not
  just on dev.

## Rationale

The rule has already decided real cases. Hybrid rank fusion lifted dev evidence coverage on 16 questions but was
worse than vector search on every held-out measure, so it is measured in every run but not used for answers. The
`bge-reranker-base` reranker raised dev coverage from 0.45 to 0.53 and lowered `test2` coverage from 0.41 to 0.36,
so it was not adopted. Without held-out splits both would have shipped.

## Consequences

- Fewer changes ship, and each one that does has evidence behind it.
- Retrieval still misses its recall and evidence-coverage targets. The method makes that visible; it does not fix it.
- Held-out splits wear out each time they are reported. `test` already has; `test2` will too.

## Risks and limits

- Small sample. Differences of a few points are noise, so only large effects can be detected.
- Relevance judgments are incomplete; `unjudged@k` reports how often unjudged papers are returned.
- One person wrote and reviewed the labels. Their judgment is built into the reference.
- Retrieval metrics say nothing about answers. Answer support has one rater and 19 claims so far
  ([handoff](../handoff.md#open-blockers)).

## When to revisit

- When `test2` has been reported often enough to be stale: add a new held-out split before the next comparison.
- When the question set grows enough to detect smaller effects, or a second reviewer joins.
- If an automated judge is added: report it separately from human review and check its agreement with the human
  ratings first.
