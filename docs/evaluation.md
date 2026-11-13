# Evaluation

How retrieval (and later, answers) is measured, what the targets are, and what the results were. The labelled
questions are in [research/evaluation/questions.jsonl](../research/evaluation/questions.jsonl); their format and
review status are described in [research/evaluation/README.md](../research/evaluation/README.md).

## Running it

```bash
make labels-check
```

```bash
make evaluate SPLIT=dev
```

`labels-check` finds every gold quotation on its stated page of the stored text and fails if any is missing.
`evaluate` runs three retrieval modes over one split (vector search, the lexical baseline, and hybrid: reciprocal
rank fusion of the two), stores an `evaluation_runs` row with per-question results, and
writes a JSON artifact to `artifacts/evaluations/` (git-ignored). The artifact records the questions file's SHA-256,
the manifest's SHA-256, the split, embedding model and revision, query instruction, chunking and extractor
settings of the indexed documents, the git commit (with `-dirty` for uncommitted changes), timestamps, and the top
results for every question.

The `test` and `test2` splits are held out: tune only on `dev`, and run `SPLIT=test2` to report (`test` has been
reported three times and is no longer fresh). Held-out splits run only from a clean checkout, so the result is tied
to a commit.

The artifacts of the runs reported below are committed in
[research/evaluation/results/](../research/evaluation/results/). Their excerpts come from the CC BY papers listed in
the corpus manifest.

## Metrics

k counts returned passages (chunks), 5 and 10. Document metrics first reduce the k passages to documents in order of
first appearance, so several chunks from one paper never count as several studies.

| Metric | Definition |
|---|---|
| `recall@k` | Share of the question's relevant documents (grade 1 or 2) that appear in the top k passages |
| `mrr@k` | 1 / position of the first relevant document among the de-duplicated documents; 0 if none |
| `ndcg@k` | Graded nDCG over de-duplicated documents, gain 2^grade − 1; unjudged documents count as 0 |
| `evidence_coverage@k` | Share of gold evidence quotations whose location on the page overlaps a returned passage |
| `unjudged@k` | Number of returned documents with no relevance judgment. High values mean the other numbers are less certain |
| `latency_ms_mean`, `latency_ms_p95` | Query embedding plus database search, per question, on CPU, model already loaded |

Only answerable and partially answerable questions are scored. Insufficient-evidence and out-of-scope questions are
kept for answer evaluation (correct and false abstention).

Not measured: anything about answers. Citation validity is enforced by the server for every answer, but whether
cited passages support the claims (answer-support review), abstention accuracy and faithfulness need generated
answers, and no LLM provider has been configured, so no answers exist to review. Automated LLM grading, if added,
will be reported as model judgment and kept apart from human review.

## Targets

Set on 2026-11-12, before the first run, for vector search on the dev split. They describe what "good enough to
build answers on" means for this corpus; they are not engineering pass/fail gates, and they will not be lowered to
make a run pass.

| Metric (dev, vector) | Target |
|---|---|
| recall@10 | ≥ 0.80 |
| mrr@10 | ≥ 0.60 |
| ndcg@10 | ≥ 0.60 |
| evidence_coverage@10 | ≥ 0.60 |

Expectation, not a target: vector search should match or beat the lexical baseline on recall@10.

Engineering gates, checked separately: every gold quotation resolves (`make labels-check`), runs are deterministic for
the same index, and query latency p95 stays under 500 ms on CPU once the model is loaded.

## Caveats

- 74 questions and 20 papers. With 37 scored dev questions one question moves an average by about 3 points, and
  with 18 scored `test2` questions by about 6; differences of a few points between runs are noise.
- Relevance judgments are incomplete: only documents an annotator considered were graded. `unjudged@k` shows how
  often the system returns documents nobody judged.
- Labels are AI drafts until a person reviews them with `make review` (see
  [research/evaluation/README.md](../research/evaluation/README.md#reviewing-labels)). Every number below was
  measured before any review. Since then 19 of the 20 `test2` labels have been reviewed and accepted unchanged
  (dataset v3), so the `test2` results stand as reported; 10 of the 43 dev labels have also been
  reviewed, unchanged; the rest of dev and all of `test` are still unreviewed.

## First answers from a real provider (dev, partial)

2026-11-13, `gemini/gemini-3.6-flash` through a private OmniRoute gateway, prompt `answer-v1`, with
[research/evaluation/experiments/answer_run.py](../research/evaluation/experiments/answer_run.py), over two days
because the provider's free tier allows only about a dozen answers a day. All 43 dev questions were attempted; 15
got a reply from the model:

| Outcome | Questions |
|---|---|
| Answered | 13 of 37 answerable; 12 cite a paper graded 2 for that question |
| "Not enough evidence" on an answerable question | 2 (q010, q015) |
| Provider unavailable (`503`, free-tier cap; one `502`) | 28, including all six no-evidence and out-of-scope questions |

- Citations mostly point at the right papers. The exception, q062, cites mcl-004 and mcl-020 (graded 1, related)
  but not mcl-017 (graded 2). Whether each cited passage supports its claim has not been reviewed by a person yet.
- Both false abstentions had passages from the right paper in the model's context (mcl-010, mcl-015). Either those
  passages lacked the actual finding (the right paper but the wrong passage, as in the retrieval results) or the
  model is too cautious; a person looking at the two answers' debug view can tell which.
- Abstention on the no-evidence and out-of-scope questions is untested: every one hit the provider limit. They did
  reach the provider, so retrieval found passages close enough to send for all six; whether the app says "not
  enough evidence" for them depends on the model.
- Generation took a median 25 s per answer (up to 77 s); the model reasons before it writes. Search took about 25 ms.
- A free tier is not enough for an answer evaluation: about 13 answers a day, then hours of cooldown. A complete run
  needs a provider with paid credits or a higher quota. `answer_run.py` resumes from its output file, so it can
  finish a run across several days, and spaces requests 15 s apart.

## Experiments (dev only)

### 2026-11-12: three ways to improve retrieval

Measured before changing any code, on the 16 scored dev questions, with
[research/evaluation/experiments/retrieval_levers.py](../research/evaluation/experiments/retrieval_levers.py).
It is read-only: other chunk sizes are built in memory from the stored page text with the project's chunker and
the pinned model. The current setup (300-token chunks, vector search) reproduces the official dev run exactly, so
the comparisons are like for like. Metrics at 10 passages unless stated.

| Variant | recall | MRR | nDCG | evidence coverage | papers in top 10 |
|---|---|---|---|---|---|
| Current: vector search, 300-token chunks | 0.82 | 0.97 | 0.88 | 0.53 | 2.6 |
| At most 3 passages per paper | 0.94 | 0.97 | 0.92 | 0.18 | 4.9 |
| At most 2 passages per paper | 0.97 | 0.97 | 0.93 | 0.18 | 6.2 |
| 150-token chunks, 20 passages (same ~3,000 tokens) | 0.89 | 1.00 | 0.95 | 0.48 | |
| 100-token chunks, 30 passages (same ~3,000 tokens) | 0.94 | 1.00 | 0.95 | 0.53 | |
| Rank fusion, vector + lexical, equal weight | 0.82 | 0.89 | 0.83 | 0.67 | |
| Rank fusion, lexical at half weight | 0.87 | 0.92 | 0.87 | 0.68 | |

What it shows:

- **A cap per paper** finds the secondary papers (recall 0.94 to 0.97) but throws away the passage that answers
  the question: evidence coverage falls from 0.53 to 0.18, so about two thirds of the gold passages vector search
  finds are the 4th or later passage from their paper. The real weakness is ranking passages within a paper, not
  variety of papers. Not adopted.
- **Smaller chunks** at the same token budget find more papers but do not improve evidence coverage. At 10 passages
  they cover less text and do worse (0.29 to 0.38). Not adopted.
- **Reciprocal rank fusion** with the lexical ranking (k = 60, 100 candidates from each) is the only change that
  lifts evidence coverage, to 0.67 or 0.68. With lexical at half weight it also raises recall (0.87) and keeps
  nDCG (0.87), at a cost to MRR (0.92: the first relevant paper is sometimes second). It is sensitive to settings:
  with 50 candidates from each ranking, the half-weight version scored recall 0.83, MRR 0.92, nDCG 0.84 and
  evidence coverage 0.61. Promising, not proven.

Caveats: 16 questions with provisional labels, so one question is about 6 points; the fusion weight and candidate
depth were picked on these same questions.

Follow-up: rank fusion was added as a third mode, `hybrid`, with these settings, and measured on both splits. On the
held-out split it was worse than vector search on every measure (see the first entry under Results), so answers
still use vector search.

### 2026-11-12: a cross-encoder reranker

A cross-encoder reads the question and a passage together, which should be better at picking the right passage
within a paper. [research/evaluation/experiments/reranker.py](../research/evaluation/experiments/reranker.py)
re-scores the top 20 or 50 vector passages and keeps the best 10. Two small open rerankers trained on MS MARCO web
search questions (Apache-2.0), on CPU, dev split, 16 questions:

| Variant | recall@10 | MRR | nDCG | evidence coverage | rerank time (median) |
|---|---|---|---|---|---|
| Vector only | 0.82 | 0.97 | 0.88 | 0.53 | |
| MiniLM-L-6 (`233902d`), top 20 | 0.82 | 0.91 | 0.85 | 0.53 | 39 ms |
| MiniLM-L-6, top 50 | 0.81 | 0.91 | 0.85 | 0.50 | 107 ms |
| MiniLM-L-12 (`7b02352`), top 20 | 0.84 | 0.90 | 0.85 | 0.53 | 68 ms |
| MiniLM-L-12, top 50 | 0.78 | 0.88 | 0.81 | 0.58 | 168 ms |

No gain. Evidence coverage stays within one question of vector search, and the first relevant paper moves down
(MRR falls from 0.97 to between 0.88 and 0.91). These models learned what a good answer to a web search looks like, not a sentence in a
physiology paper. Not adopted; nothing was changed in the app.

Where this leaves retrieval: four cheap levers (a cap per paper, smaller chunks, rank fusion, a small reranker) and
none beats plain vector search robustly. With 16 provisional dev questions, a real difference of a few points is
indistinguishable from noise. Reviewing the labels and adding questions would make the next comparison worth more
than another experiment would.

### 2026-11-12: both experiments re-run on dataset v2 (37 scored dev questions)

The same scripts, unchanged, on the larger dev split. Top 10 passages unless stated.

| Variant | recall | MRR | nDCG | evidence coverage |
|---|---|---|---|---|
| Vector only (current) | 0.76 | 0.90 | 0.80 | 0.45 |
| At most 2 passages per paper | 0.90 | 0.90 | 0.85 | 0.20 |
| 100-token chunks, 30 passages (same ~3,000 tokens) | 0.91 | 0.87 | 0.85 | 0.41 |
| Rank fusion, lexical at half weight | 0.77 | 0.80 | 0.73 | 0.48 |
| Reranker MiniLM-L-12, top 20 | 0.79 | 0.85 | 0.79 | 0.45 |
| Reranker MiniLM-L-6, top 20 | 0.77 | 0.83 | 0.77 | 0.43 |
| Reranker bge-reranker-base (`2cfc18c`), top 20 | 0.80 | 0.79 | 0.73 | 0.53 |
| Reranker bge-reranker-base, top 50 | 0.76 | 0.77 | 0.69 | 0.39 |

The conclusions hold, and one changes in size: rank fusion's dev advantage in evidence coverage shrinks from 0.15
(16 questions) to 0.03 (37 questions) while it still costs 0.10 of MRR. Most of the earlier gain was the small
question set, which is also why it did not hold on either held-out split. None of the cheap levers improves on plain
vector search.

The larger general reranker, `BAAI/bge-reranker-base` (MIT, about 1.1 GB, trained on broader data than MS MARCO),
is the first option to move evidence coverage by more than a question or two: re-scoring the top 20 vector passages
raises it from 0.45 to 0.53 and recall from 0.76 to 0.80. It is a trade-off, not a clean win. The paper that
answers the question drops down the list (MRR 0.90 to 0.79, nDCG 0.80 to 0.73), it takes a median 234 ms per
question on CPU, and at depth 50 it is worse on everything (evidence coverage 0.39), so the result depends on a
setting chosen on these questions. For answers, which use the passages rather than the paper order, it is the most
promising option so far. Not adopted: it would need a check on `test2` and then an answer-level comparison once an
LLM provider is configured.

Held-out check, run once at commit `ba61ba8` with only the setting chosen on dev (bge-reranker-base, top 20), on the
18 scored `test2` questions:

| Variant (test2) | recall@10 | MRR | nDCG | evidence coverage |
|---|---|---|---|---|
| Vector only (same as the official test2 run) | 0.77 | 0.81 | 0.72 | 0.41 |
| bge-reranker-base, top 20 | 0.76 | 0.91 | 0.75 | 0.36 |

The dev gain did not hold. On fresh questions the reranker ranked the answering paper higher (MRR 0.81 to 0.91) and
found the answering passage less often (evidence coverage 0.41 to 0.36): the opposite of what it did on dev. Each
change is one or two questions and the direction flips between splits, so there is no reliable gain. Not adopted.
With this, none of the five options tried beats plain vector search on held-out questions.

## Results

### 2026-11-12, dataset v2 (74 questions), runs at commit be07843

44 new questions (see [research/evaluation/README.md](../research/evaluation/README.md#current-set)) and a fresh
held-out split, `test2`, which nothing has been tuned on. Same corpus, index and settings as the entries below.

| Metric | Dev, vector | Dev, hybrid | Dev, lexical | Test2, vector | Test2, hybrid | Test2, lexical | Target (vector) |
|---|---|---|---|---|---|---|---|
| Questions scored | 37 | 37 | 37 | 18 | 18 | 18 | |
| recall@5 | 0.70 | 0.62 | 0.41 | 0.63 | 0.64 | 0.36 | |
| recall@10 | 0.76 | 0.77 | 0.52 | 0.77 | 0.75 | 0.48 | ≥ 0.80: **missed** on both |
| mrr@10 | 0.90 | 0.80 | 0.51 | 0.81 | 0.83 | 0.51 | ≥ 0.60: met |
| ndcg@10 | 0.80 | 0.73 | 0.42 | 0.72 | 0.72 | 0.38 | ≥ 0.60: met |
| evidence_coverage@10 | 0.45 | 0.48 | 0.19 | 0.41 | 0.33 | 0.15 | ≥ 0.60: **missed** on both |
| unjudged@10 | 1.4 | 1.5 | 3.0 | 1.7 | 1.6 | 2.1 | |

Runs: dev `8d1e6f28`, test2 `f0b58fb5`, artifacts in `research/evaluation/results/`. Vector latency p95 was 22 ms
on dev and 34 ms on test2; the lexical and hybrid means on dev were inflated by Docker stalls again.

- The larger dev split is harder than the original 16 scored questions: vector recall@10 0.82 there, 0.76 here, and
  evidence coverage 0.53 there, 0.45 here. The first numbers were optimistic, not wrong; with twice the questions
  the new ones are the better estimate.
- On the fresh `test2` split, vector search scores like it does on dev (recall@10 0.77, evidence coverage 0.41),
  which suggests the dev numbers are representative.
- Hybrid is not better than vector on fresh questions: about the same recall, MRR and nDCG, and lower evidence
  coverage (0.33 against 0.41). Together with the earlier `test` result, that settles it for now: answers stay on
  vector search.
- The weak spot is unchanged and now measured on 55 questions: the right paper is usually found (MRR 0.81 to 0.90),
  the right passage much less often (evidence coverage 0.41 to 0.45).

### 2026-11-12, dataset v1, hybrid search added, runs at commit fe8c371

The same dataset, corpus and index as the entry below. New: `hybrid`, reciprocal rank fusion (k = 60) of the top 100
vector and top 100 lexical passages, lexical at half weight. Those settings were chosen on the dev split in the
experiment above, before the test split was run with them.

| Metric | Dev, vector | Dev, hybrid | Test, vector | Test, hybrid |
|---|---|---|---|---|
| Questions scored | 16 | 16 | 9 | 9 |
| recall@5 | 0.76 | 0.74 | 0.48 | 0.48 |
| recall@10 | 0.82 | 0.87 | 0.62 | **0.54** |
| mrr@10 | 0.97 | 0.92 | 0.91 | **0.84** |
| ndcg@10 | 0.88 | 0.87 | 0.77 | **0.70** |
| evidence_coverage@10 | 0.53 | 0.68 | 0.61 | **0.50** |
| unjudged@10 | 0.75 | 0.88 | 1.9 | 1.9 |

Runs: dev `49444502`, test `a235cd90`, artifacts in `research/evaluation/results/`. Vector and lexical numbers are
identical to the entry below.

- On dev, where its settings were chosen, hybrid raised evidence coverage (0.53 to 0.68) and recall (0.82 to 0.87).
  On the held-out split it was worse than vector search on every measure. With 9 test questions that is one or two
  questions per metric, but the direction is consistent, and it is what overfitting the dev split looks like.
- Answers keep using vector search. Hybrid stays as a measured mode, so it can be re-checked once the labels are
  reviewed and there are more questions.
- Latency: hybrid costs about the same as the lexical query it contains. Timed directly, seven times each with the
  model loaded: median 19 ms for vector, 212 ms for lexical, 245 ms for hybrid. The p95 figures in these runs (up
  to 33 s for hybrid on dev) were Docker Desktop stalling while other projects' containers were busy; vector search
  had multi-second outliers in the same minutes.

### 2026-11-12, dataset v1, tie order fixed, runs at commit d830fa8

The same dataset, corpus, index and settings as the runs below. One thing changed: passages with equal scores are now
ordered by paper (the file's SHA-256), then by position in the paper. Before, they were ordered by chunk ID, a random
UUID created at ingestion, so a fresh ingest of the same corpus could reorder them; the fresh-clone check in
milestone 6 got dev lexical recall@10 0.70 where the main stack got 0.67. This is a determinism fix, not tuning:
the new order was chosen before these runs and nothing else was changed.

| Metric | Dev, vector | Dev, lexical | Test, vector | Test, lexical | Target (vector) |
|---|---|---|---|---|---|
| Questions scored | 16 | 16 | 9 | 9 | |
| recall@5 | 0.76 | 0.59 | 0.48 | 0.43 | |
| recall@10 | 0.82 | 0.70 | 0.62 | 0.52 | ≥ 0.80: dev met, **test missed** |
| mrr@10 | 0.97 | 0.64 | 0.91 | 0.61 | ≥ 0.60: met |
| ndcg@10 | 0.88 | 0.53 | 0.77 | 0.53 | ≥ 0.60: met |
| evidence_coverage@10 | 0.53 | 0.29 | 0.61 | 0.22 | ≥ 0.60: **dev missed**, test met |
| unjudged@10 | 0.75 | 2.6 | 1.9 | 2.7 | |
| latency mean / p95 (ms) | 26 / 140 | 292 / 867 | 24 / 59 | 201 / 224 | p95 < 500: met |

Runs: dev `f74849d9`, test `ed76f18f`. A repeat dev run (`1c85eb84`) returned the same passages for every question.

- Vector search returned exactly the same passages in the same order as before for every question on both splits,
  so its numbers are unchanged. Exact distance ties practically never happen.
- Lexical ties are common: the lexical top 10 changed for 18 of 19 dev questions and 10 of 11 test questions. Dev
  recall@10 went from 0.67 to 0.70 and test from 0.57 to 0.52; mrr@10 and ndcg@10 moved by 0.02 at most. These
  are the numbers any ingest of the same PDFs with the same settings now gives.
- Vector search still beats the lexical baseline on every measure on both splits.
- The dev latencies were measured while Docker Desktop was stalling (other projects' containers were busy). Timing
  the lexical query alternately with the old and new order gave the same median, 212 and 216 ms; both had
  multi-second outliers. The test run had no stall.

### 2026-11-12, dataset v1, final runs at commit 3294220

Lexical columns superseded by the runs above: they depended on the random tie order. Vector metrics are unchanged.

Dataset v1 (questions `9b456455`, manifest `e68d33b4`), 20 papers searchable (1,269 chunks of up to 300 tokens with 40
overlap), bge-small-en-v1.5 at 5c38ec7, k = 10 passages. Labels: 0 of 30 reviewed by a person.

| Metric | Dev, vector | Dev, lexical | Test, vector | Test, lexical | Target (vector) |
|---|---|---|---|---|---|
| Questions scored | 16 | 16 | 9 | 9 | |
| recall@5 | 0.76 | 0.59 | 0.48 | 0.43 | |
| recall@10 | 0.82 | 0.67 | 0.62 | 0.57 | ≥ 0.80: dev met, **test missed** |
| mrr@10 | 0.97 | 0.65 | 0.91 | 0.61 | ≥ 0.60: met |
| ndcg@10 | 0.88 | 0.54 | 0.77 | 0.55 | ≥ 0.60: met |
| evidence_coverage@10 | 0.53 | 0.29 | 0.61 | 0.22 | ≥ 0.60: **dev missed**, test met |
| unjudged@10 | 0.75 | 2.5 | 1.9 | 2.4 | |
| latency mean / p95 (ms) | 22 / 62 | 217 / 249 | 25 / 67 | 201 / 218 | p95 < 500: met |

Runs: dev `073caed6`, test `34338c4e` and `79255868`. The two test runs gave identical metrics. The first test run
measured a vector p95 of 1,083 ms: with 11 queries the p95 is the slowest one, and one query hit a stall in Docker
Desktop (seen throughout this session, while other projects' containers used several CPUs). The repeat measured 67
ms, which is the figure above.

What the held-out split shows:

- The paper that answers the question is found: 9 of the 10 papers graded 2 appear in the top 10 (18 of 19 on dev),
  and the first relevant paper is almost always ranked first (MRR 0.91).
- Recall misses come from secondary papers: only 5 of 13 papers graded 1 ("related or partial") are found on test,
  12 of 19 on dev. The top 10 passages cover only 3.4 distinct papers on test (2.6 on dev), because a strong paper
  fills several of the 10 places with its own chunks. The one missed grade-2 paper is in a synthesis question
  (q022), which needs two papers.
- Evidence coverage is higher on test than on dev, 0.61 against 0.53; with 9 and 16 questions that difference is
  within noise. Both say the same thing as before: the right paper is often found through the wrong passage.
- Vector search beats the lexical baseline on every measure on both splits.

The test result is reported as measured; nothing was tuned after it. Levers to try on dev, then confirm on a new
held-out set: limit passages per paper in the top k (more distinct papers), smaller or sentence-aware chunks, and
hybrid vector plus lexical ranking.

### 2026-11-12, dev split, first run (run 3e6a4009, same numbers as the dev run at commit 3294220)

Lexical column superseded by the runs at commit d830fa8 (random tie order).

16 answerable dev questions scored, k = 10 passages, 20 papers searchable (1,269 chunks, 300-token chunks with 40
overlap), bge-small-en-v1.5 at 5c38ec7, all labels provisional.

| Metric | Vector | Lexical baseline | Target (vector) |
|---|---|---|---|
| recall@5 | 0.76 | 0.59 | |
| recall@10 | 0.82 | 0.67 | ≥ 0.80, met |
| mrr@10 | 0.97 | 0.65 | ≥ 0.60, met |
| ndcg@10 | 0.88 | 0.54 | ≥ 0.60, met |
| evidence_coverage@5 | 0.28 | 0.15 | |
| evidence_coverage@10 | 0.53 | 0.29 | ≥ 0.60, **missed** |
| unjudged@10 (documents per question) | 0.75 | 2.5 | |
| latency mean / p95 (ms) | 20 / 60 | 207 / 229 | p95 < 500, met |

What it shows:

- Vector search finds the right papers: the first relevant paper is almost always ranked first (MRR 0.97). The
  lexical baseline is clearly worse on every measure and returns far more unjudged documents.
- It often returns the right paper but the wrong passage. For q001 and q015, the paper's first page was retrieved, but
  as its opening chunks (title and background), while the gold sentence sits in a later chunk of the same page. Of the
  8 dev questions with incomplete evidence coverage, 5 still had recall@10 of 1.0 or close to it.
- Runs are deterministic: a second run gave identical metrics.

Not tuned yet. The obvious levers, to try on dev only: smaller chunks, sentence-aware chunk boundaries, and more
candidates per paper before passages are chosen. The held-out test split has not been run.
