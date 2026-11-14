# Handoff

State of Masters Cycling Lab at the end of milestone 6, on 2026-11-12, updated 2026-11-14 for the first real answers
and the finished label review. Everything below was run, not assumed; anything not verified says so. The checks
table records the fresh-clone run of 2026-11-12 as it happened.

## What works

- **Documents:** upload PDFs (browser, API or `make ingest`), duplicate detection by SHA-256, durable background
  ingestion with leases, retries and stable failure codes, page text with extraction warnings, metadata corrections,
  reindex without downtime, permanent deletion.
- **Search:** exact cosine search over pinned bge-small-en-v1.5 embeddings, with a lexical baseline and a hybrid
  mode (rank fusion of both) that every evaluation run measures, filters by
  document and publication year, scores labelled as ordering only.
- **Answers:** passages labelled `E1..En`, a versioned prompt, strict JSON validation with one repair attempt,
  citations built from stored snapshots, abstention without calling the model when evidence is missing, `502`/`503`
  for provider problems. Works with any OpenAI-compatible endpoint; checked with `gemini/gemini-3.6-flash` on a free
  tier (`make test-live` passes; a partial dev answer run, see [evaluation.md](evaluation.md)).
- **Workspace:** Ask a question (claims, citation passages, PDF at the physical page), Papers, Search details
  (including how an answer was built) and Search scores pages.
- **Evaluation:** 74 labelled questions (43 dev, 11 held-out test, 20 fresh held-out test2) over 20 CC BY papers,
  gold quotations anchored to paper, physical page and exact text; recall, MRR, nDCG, evidence coverage, unjudged
  count and latency for vector, lexical and hybrid search; JSON artifacts with full provenance.
- **Operations:** `make backup` / `make restore`, `make smoke`, readiness checks, a label review workflow
  (`make review`).

## Setup and run

From a fresh clone (details in the [README](../README.md) and [operations](operations.md)):

```bash
cp .env.example .env
```

Set your own `POSTGRES_PASSWORD` in `.env`, and the same password in `DATABASE_URL`. Then:

```bash
make bootstrap
```

```bash
make up
```

```bash
make migrate
```

```bash
make download-model
```

```bash
make corpus-download
```

```bash
make corpus-ingest
```

```bash
make evaluate SPLIT=dev
```

Open http://127.0.0.1:8080. To enable answers, set `LLM_BASE_URL`, `LLM_MODEL` and, if the provider needs one,
`LLM_API_KEY` in `.env`, then run `make up` again.

## Checks run

A fresh clone of commit `3294220`, run on 2026-11-12 in its own Compose project and volumes (so it could not reuse
anything from the main stack), with `.env` made from `.env.example` and a new password:

| Step | Result |
|---|---|
| `make bootstrap`, `lint`, `typecheck`, `build`, `check-api-types` | Pass |
| `make test` | 94 backend and 15 frontend tests pass |
| `make up`, `make migrate` | Pass |
| `make download-model` | Killed once (exit 137, most likely memory: the Docker VM was shared with other projects); passed on the rerun |
| `make corpus-download`, `make corpus-verify` | 20 PDFs downloaded from PMC, all match the manifest |
| `make corpus-ingest` | 18 of 20 papers indexed; the worker was killed repeatedly (no error in its log, most likely memory) and 2 papers ended in `WORKER_LOST`. Both indexed on Reindex (peak worker memory about 550 MB) |
| `make ingest FILE=...` (a corpus PDF) | Recognised as a duplicate |
| `make labels-check` | All 38 gold quotations found on their pages |
| `make evaluate SPLIT=dev` / `SPLIT=test` | Vector metrics identical to the main stack on both splits; lexical identical on test, different on dev (see below) |
| `make smoke` | Pass (answer step skipped: `LLM_NOT_CONFIGURED`) |
| `make test-integration`, `make test-model` | 70 and 5 tests pass |
| `make test-live` | Skipped: no credentials |
| `make backup` → delete a paper → `make restore` | Typing anything but `restore` changes nothing. After restoring: 20 of 20 papers searchable, the deleted paper back with the same SHA-256 and page text, both evaluation runs back, labels-check and smoke pass, dev metrics identical to before |

Host-side commands also hit Docker connection timeouts (15 s) a few times and passed on a rerun; Docker Desktop on
this machine was sharing its VM with other projects' containers, some of which Docker itself killed for memory.

Two real problems found and handled:

- **Restore left the browser with 502s.** nginx looked up the API's address once at startup; the restored API
  container came back on a new address. nginx now asks Docker's DNS again (cached 10 s). Verified by forcing a new
  API address on the main stack: requests recovered within about 10 seconds. The same bug would have hit `make up`
  after changing `.env`, for example to add LLM settings.
- **The lexical baseline did not reproduce across ingestions.** Tied keyword scores were ordered by chunk ID, a
  random UUID per ingestion, so a fresh ingest gave dev lexical recall@10 0.70 instead of 0.67. Vector search
  reproduced exactly, because exact distance ties practically never happen. Fixed after milestone 6: ties in both
  modes now go by paper SHA-256, then chunk position. Both splits were re-run: vector results unchanged, lexical
  recall@10 0.70 on dev and 0.52 on test (was 0.57). See [evaluation.md](evaluation.md#results).

On the main stack, separately: `make lint`, `typecheck`, `test`, `build`, `check-api-types`, `corpus-verify`,
`labels-check`, both evaluations and `make backup` pass; `make smoke` passed in milestone 5 and again in the fresh
run.

## Corpus and evaluation

20 open-access papers (CC BY) on masters and older cyclists, training and physiology: 259 pages, 1,269 chunks.
Provenance, licence and SHA-256 for each are in [research/corpus/manifest.jsonl](../research/corpus/manifest.jsonl);
population notes are provisional.

Latest retrieval results, dataset v2 (74 questions), vector search (details and earlier runs in
[evaluation.md](evaluation.md)):

| Metric | Dev (37 scored) | Fresh held-out test2 (18 scored) | Target |
|---|---|---|---|
| recall@10 | 0.76 | 0.77 | ≥ 0.80 |
| mrr@10 | 0.90 | 0.81 | ≥ 0.60 |
| ndcg@10 | 0.80 | 0.72 | ≥ 0.60 |
| evidence_coverage@10 | 0.45 | 0.41 | ≥ 0.60 |
| latency p95 | 22 ms | 34 ms | < 500 ms |

The paper that answers a question is usually found and ranked near the top; the passage that answers it much less
often, so recall and evidence coverage miss their targets on both splits. Dev and fresh held-out numbers agree,
which suggests the dev numbers are representative. Vector search beats the lexical baseline on every measure; hybrid ranking is no better on fresh
questions. These numbers were measured before the label review; every label has since been reviewed by a person and
accepted unchanged (dataset v5), so they stand as reported.

## Open blockers

1. **The answer evaluation is partial.** `make test-live` passes with `gemini/gemini-3.6-flash` through OmniRoute,
   but the free tier allows about a dozen answers a day: 15 dev replies with 6 passages and 7 with 10 so far (see
   [evaluation.md](evaluation.md#first-answers-from-a-real-provider-dev-partial)). Untested: abstention on the six
   no-evidence and out-of-scope dev questions (and the four in the other splits), synthesis and population-mismatch
   answers, any held-out answers, and the browser's ask → cited answer path with a real model. Needs: a provider
   with paid credits or a higher quota.
2. **Answer support has one rater on a small, easy sample.** KC rated the 19 claims of the first 7 answers (all
   supported). These are direct questions rated by the person who built the system. Needs: the remaining answers
   rated, ideally by a second person, before quoting a support rate.

Resolved on 2026-11-13: every one of the 74 labels has been reviewed by a person and accepted unchanged (dataset v5).

## Acceptance criteria not met

- Milestone 5: the "ask" step of upload → ready → ask → inspect passage → open PDF has been checked in the browser
  only with a stubbed API; real answers so far came from `answer_run.py` (blocker 1). The other steps were checked
  in the browser.
- Milestone 6: answer-support review covers only the first 7 answers (blockers 1 and 2).
- Retrieval targets, which are quality goals rather than gates: recall@10 (0.76 dev, 0.77 test2; target 0.80) and
  evidence coverage@10 (0.45 dev, 0.41 test2; target 0.60) missed.

## Known limitations

- Local, single-user, no authentication. Do not expose it beyond `127.0.0.1`.
- No OCR: scanned PDFs fail with `OCR_REQUIRED`. Two-column pages can interleave, tables lose their layout, figures
  are skipped.
- Chunks never cross pages, so a sentence that runs over a page break is split.
- Deleting a document removes its file, index and the answers that quoted it, but older evaluation runs keep up to
  300 characters of each passage they returned.
- With 37 scored dev and 18 scored test2 questions, one question moves an average by about 3 and 6 points.
- Docker Desktop on this machine stalls for several seconds now and then and ran short of memory while other
  projects' containers were up; the app itself answers in milliseconds. Latency figures come from runs without a
  stall.

## Next steps, in order

1. Rate whether each cited passage supports its claim with `rate_answers.py` (see
   [research/evaluation/README.md](../research/evaluation/README.md#rating-answers)). The first 7 answers with 10
   passages are rated (19 of 19 claims supported); rate the rest as the nightly run adds them, and record the counts
   in docs/evaluation.md.
2. Finish the dev answer run with 10 passages (the scheduled task does this on the free tier) and check abstention
   on the six no-evidence and out-of-scope questions, still untested. All 74 labels are reviewed
   and none changed (dataset v5). Record a new dataset version when labels change.
3. Improve how passages are chosen within the right paper, the main retrieval weakness. Tried on dev: a cap per
   paper and smaller chunks did not help; rank fusion with the lexical ranking helped on dev but was worse than
   vector search on every held-out measure, so it is measured in every run (`hybrid`) but not used for answers (see
   [evaluation.md](evaluation.md#experiments-dev-only)). Two small MS MARCO cross-encoder rerankers did not help
   either. Re-run on the 37 scored dev questions of dataset v2, both experiments reach the same conclusions, and
   fusion's earlier dev gain mostly disappears. A larger general reranker, `BAAI/bge-reranker-base` (MIT, about
   1.1 GB), re-scoring the top 20 raised dev evidence coverage from 0.45 to 0.53, but on the held-out `test2` it
   lowered it (0.41 to 0.36) while raising MRR, so it is not adopted either. None of the five options beats plain
   vector search on held-out questions. The next useful step for retrieval is the reviewed labels (step 2), then an
   answer-level comparison once answers exist, rather than another ranking experiment.
4. Answer evaluation: [answer_report.py](../research/evaluation/experiments/answer_report.py) summarises an answer
   run (abstention, grade-2 papers cited, citations on a gold page). Still missing: human ratings of whether each
   cited passage supports its claim, and a CLI command once the report's shape has settled.
