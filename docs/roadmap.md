# Roadmap

Masters Cycling Lab is built in seven milestones. Each one ends with the app runnable and its checks passing.
Later milestones start only when the earlier ones pass their acceptance checks.

| Milestone | Scope | Status |
|---|---|---|
| 0 | Repository, design, dependency plan | Done |
| 1 | Compose, migrations, schema, storage, readiness | Done |
| 2 | Durable PDF ingestion | Done |
| 3 | Retrieval and first research validation | Done |
| 4 | Grounded answers with citations | Done (live provider test blocked: no credentials) |
| 5 | React workspace | Done (cited answers checked with a stubbed API only: no credentials) |
| 6 | Evaluation and handoff | Done (labels not human-reviewed; answers not evaluated: no credentials) |

The MVP is not complete until milestone 6 passes on a real corpus. Placeholder code, a fabricated corpus,
untraceable citations or checks that were never run do not count.

## Assumptions

- One user on one machine. No authentication. Remote or shared hosting needs auth first.
- CPU only. One API process and one ingestion worker.
- PDFs come from you or from openly licensed sources. The app never fetches URLs on the server.
- Answer generation uses any OpenAI-compatible `/chat/completions` endpoint you configure. Everything except
  answering works without one.
- Gold evaluation labels need a human reviewer. Labels drafted with AI help stay marked `provisional` until
  someone checks them against the PDF.

## Blockers to plan around

These are outside the code and can stall acceptance:

1. **Corpus.** 20 legitimate papers with full text you are allowed to use. Open-access sources (PubMed Central
   OA subset, journal CC-BY articles) or PDFs you already have. Milestone 3 ships an acquisition checklist if
   this is not ready.
2. **LLM credentials.** Needed for milestone 4's live smoke test and for answer evaluation in milestone 6.
3. **Human review time.** At least 25 labeled questions, every gold quotation checked against the actual PDF page.

## Milestone 0: repository and design (done)

- Backend scaffold: validated settings, error envelope, request IDs, `GET /api/v1/health/live`, OpenAPI export.
- Frontend scaffold: Vite, React, TypeScript, Vitest, types generated from the backend's OpenAPI file.
- Exact dependency pins with `backend/uv.lock` and `frontend/package-lock.json`. See [dependencies.md](dependencies.md).
- Decisions recorded in [decisions/](decisions/). Architecture in [architecture.md](architecture.md).
- Commands: `make bootstrap`, `make lint`, `make typecheck`, `make test`, `make build`.

## Milestone 1: persistence and infrastructure (done)

- `compose.yaml`: `db` (pgvector 0.8.7 on PostgreSQL 17), one-shot `migrate`, `api`, and `frontend` (nginx serving
  the build and proxying `/api`). Published ports on `127.0.0.1` only, named volumes, health checks, non-root
  containers. The `worker` service is added with the worker itself in milestone 2.
- SQLAlchemy engine and Alembic. The first migration creates the `vector` extension and all 13 tables. No
  `create_all()` anywhere; a test fails if models and migrations drift apart.
- Invariants enforced by PostgreSQL: one active ingestion job per document, a document's active index must be one
  of its own versions, chunk spans stay inside one index version, citations can only point at evidence from their
  own query run, a fixed `vector(384)` column, and deleting a document with query history fails unless that
  history is purged on purpose.
- Local file storage: generated keys, atomic writes, size limit while streaming, no user-controlled paths.
- `GET /api/v1/health/ready`: database, migrations, `vector` extension and storage. LLM shown as configured or not;
  the provider is never called.
- `Host` allow-list (blocks DNS rebinding) and an `Origin` check on browser writes.
- `make check-api-types` fails when `backend/openapi.json` or the generated frontend types are stale. Checks run
  locally; pull requests also run lint, typecheck, offline tests and this check in GitHub Actions.

Verified: fresh database migrates; downgrade and re-upgrade work; 31 integration tests on constraints, migrations
and readiness pass; data in both volumes survived `make down && make up`. See [operations.md](operations.md).

## Milestone 2: durable ingestion (done)

- Document API: upload (content-checked PDF, size limit enforced before the body is read, SHA-256 dedupe: `202` new,
  `200` duplicate), list, get, metadata corrections, original file, page text, reindex, delete. Ingestion job status.
- Worker service: PostgreSQL queue with `FOR UPDATE SKIP LOCKED`, five-minute leases renewed on every write, a new
  claim token per attempt checked inside every write (fencing), bounded retries with backoff, `WORKER_LOST` after
  repeated crashes, permanent failures with stable codes (`PDF_ENCRYPTED`, `PDF_CORRUPT`, `OCR_REQUIRED`,
  `PDF_TOO_MANY_PAGES`, `MODEL_MISMATCH`...).
- PyMuPDF extraction per physical page with printed labels kept separately; pages without text are kept empty with a
  warning, and a PDF with no text at all fails with `OCR_REQUIRED`.
- Conservative removal of repeated first/last lines (running headers, footers, page numbers), recorded as page
  warnings.
- Page-local chunks of up to 300 model tokens with 40 tokens of overlap, cut on word boundaries, each with a span
  back to its page; every chunk is re-counted against the model's 512-token limit before embedding.
- Batched CPU embeddings with the pinned bge-small model; the new index version is activated in one transaction and
  the previous one retired. A failed rebuild leaves the old version active.
- Deletion: hidden and jobs canceled at once, then file, index data and any answer history that quoted it removed.
- `make download-model`, `make ingest FILE=...`, `make test-model`.

Verified: unit, integration (real PostgreSQL, real PDFs, test embedder) and real-model tests; a generated PDF went
through `make ingest` in Docker to `ready`, reindexed (old version retired), and was deleted with no files or rows
left. Readiness does not check the embedding model yet: the API only needs it once search exists (milestone 3).

## Milestone 3: retrieval and first validation (done)

- Exact cosine search with pgvector over active, ready index versions only, ignoring vectors from any other model;
  document and publication-year filters; ties broken by chunk ID; `POST /api/v1/retrieval/search` returns rank,
  distance, similarity, pages with offsets, model and timings, and says scores are not probabilities.
- The API loads the embedding model once, on first search; readiness reports whether the model files are present.
- Lexical baseline (PostgreSQL full-text search, OR of query words) behind the same interface.
- Corpus: 20 CC BY papers with manifest, provisional population notes, and download/verify/ingest commands. See
  [research/corpus/README.md](../research/corpus/README.md).
- 30 labelled questions (19 dev, 11 held-out test) of five types, gold quotations anchored to paper, physical page
  and exact text, every one checked by `make labels-check`. All provisional AI drafts awaiting human review.
- Metrics (recall, MRR, graded nDCG, evidence-span coverage, unjudged count, latency), `make evaluate SPLIT=dev`,
  JSON artifacts with full provenance, `GET /api/v1/evaluation-runs`.

First dev run: vector search met the recall, MRR and nDCG targets and missed evidence coverage (0.53 vs 0.60); it
beat the lexical baseline on every measure. Details and analysis in [evaluation.md](evaluation.md).

## Milestone 4: grounded answers (done, except the live provider check)

- `POST /api/v1/answers`, `GET /api/v1/answers/{id}`, `GET /api/v1/answers/{id}/debug`.
- Provider adapter for any OpenAI-compatible `/chat/completions` endpoint with a minimal contract: `model`,
  `messages`, `temperature`, `max_tokens`, reply text in `choices[0].message.content`. No JSON mode, tools or usage
  reporting is required; usage is stored only when the provider reports it.
- Versioned prompt (`answer-v1`): passages are labelled `E1..En`, wrapped as untrusted quoted evidence (they can't close
  or forge an evidence block), and the model is told to separate findings, limitations and population mismatch.
- Context selection in rank order: overlapping passages skipped, at most `RETRIEVAL_CONTEXT_K` (10; 6 until 2026-11-13), within a token budget
  that reserves room for instructions, question and output. Every candidate is stored with the reason it was or wasn't
  sent, plus a snapshot of exactly the text that was sent.
- Strict validation: valid JSON, every claim cites only labels that were sent, `answered` needs claims. One repair
  attempt, then `502 GENERATION_INVALID`. Citations (titles, pages, excerpts, file links) come from the stored
  snapshot, never from model text. No usable evidence: `insufficient_evidence` without calling the model. Provider
  down or not configured: `503`, never an abstention.
- Blocked: `make test-live` (real provider) needs `LLM_BASE_URL` and `LLM_MODEL`; none are configured, so it skips.

## Milestone 5: React workspace (done, except a cited answer from a real provider)

- **Research:** ask a question, optionally limited by publication year. Each claim carries citation buttons; the
  selected one shows the passage, title, authors, pages (physical and printed) and a link that opens the original
  PDF at the physical page. "Not enough evidence" and a service failure (`502`/`503`) look different, and the
  failure says it is not a finding about the research.
- **Documents:** upload, indexing status with stage and progress (polled only while a job is queued or running),
  failure codes, title and year corrections, page text with extraction warnings, reindex, and delete after a
  confirmation.
- **Search details page:** search in vector or lexical mode with distance, similarity or lexical score, model,
  revision and timings. "How this answer was built" shows every candidate passage, whether it was sent to the model
  and why.
- **Evaluations:** runs with vector and lexical metrics side by side, per-run detail with every metric, latency and
  per-question scores and top hits. Labelled as automated retrieval metrics, not answer quality.
- Types come from `backend/openapi.json`; `make check-api-types` fails if they drift. Hash routing, a skip link,
  labelled controls, visible focus, light and dark themes. No research content is built into the frontend.
- `make smoke`: upload → indexed → search → page text → original file → answer → delete, against the running
  stack.

Verified: 15 frontend tests (views against a stubbed API: cited answer, abstention, `503`, document states, upload,
delete confirmation, a failed metadata save, retrieval, evaluations, navigation), lint, typecheck, build; `make smoke` passed against Docker
with the answer step skipped (`LLM_NOT_CONFIGURED`). Checked by hand in a browser against the 20-paper corpus: the
document list, page viewer, retrieval search, evaluation runs, and a question submitted from the keyboard showing the
`503` failure; a file link with `#page=3` opened the PDF on page 3. Upload and delete in the UI are covered by the
view tests (and the same API calls by `make smoke`). A successful metadata edit and a reindex from the UI have no
test yet and were not tried by hand, to leave the corpus as it is.
Blocked: a cited answer in the browser from a real provider needs `LLM_BASE_URL` and `LLM_MODEL`.

## Milestone 6: evaluation and handoff (done, with the two blockers above still open)

- Dataset v1 frozen by SHA-256 (questions and manifest) with fixed split membership; the test split runs only from a
  clean checkout so every held-out result names a commit.
- Final dev and first held-out test runs, artifacts committed in `research/evaluation/results/`, reported with
  analysis in [evaluation.md](evaluation.md). Test recall@10 0.62 missed its target; dev evidence coverage 0.53
  missed its target. Nothing was tuned on test.
- Human review workflow: `make review` shows each provisional question with its gold quotations in page context and
  a PDF link, and records `reviewed_by`, `reviewed_on` and notes. Runs record how many labels were reviewed (0 of 30
  so far).
- `make backup` / `make restore`, deletion behaviour and what deletion does not remove, in
  [operations.md](operations.md). Worker recovery was already documented there.
- [Handoff](handoff.md): what works, checks run, results, unmet criteria, next steps.

Verified: every README and Makefile command from a fresh clone in its own Compose project, including corpus
download and ingest, both evaluations (vector metrics identical to the main stack), smoke, integration and model
tests, and a backup → delete → restore cycle. Steps that failed because Docker ran out of memory or timed out passed
on a rerun; two papers needed a reindex. Details in [handoff.md](handoff.md#checks-run). The run found that restore
left nginx pointing at the API's old address (fixed: nginx now re-resolves it) and that lexical results depend on
random chunk IDs for ties (fixed afterwards: ties go by paper SHA-256, then chunk position).

Not done: answer-support review (no answers without a provider) and human label review (needs a person).

## Out of scope for the MVP

OCR, hybrid retrieval, reranking, HNSW indexes, streaming answers, FIT uploads, activity sync and training
metrics. The [architecture](architecture.md#future-training-module) describes where training analytics would go
later.
