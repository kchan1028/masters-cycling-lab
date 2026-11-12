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
`evaluate` runs both retrieval modes over one split, stores an `evaluation_runs` row with per-question results, and
writes a JSON artifact to `artifacts/evaluations/` (git-ignored). The artifact records the questions file's SHA-256,
the manifest's SHA-256, the split, embedding model and revision, query instruction, chunking and extractor
settings of the indexed documents, the git commit (with `-dirty` for uncommitted changes), timestamps, and the top
results for every question.

The test split is held out: tune only on `dev`, and run `SPLIT=test` to report.

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
kept for answer evaluation in milestone 4 (correct and false abstention).

Not measured yet: citation validity, claim support and faithfulness (milestone 4), and human ratings (milestone 6).
Automated LLM grading, if added, will be reported as model judgment and kept apart from human review.

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

- 30 questions and 20 papers. A single question moves an average by 4 to 6 points; differences of a few points
  between runs are noise.
- Relevance judgments are incomplete: only documents an annotator considered were graded. `unjudged@k` shows how
  often the system returns documents nobody judged.
- All labels are provisional AI drafts until a person reviews them (see the review workflow).

## Results

### 2026-11-12, dev split, first run (run 3e6a4009)

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
