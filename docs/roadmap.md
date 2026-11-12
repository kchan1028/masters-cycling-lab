# Roadmap

Masters Cycling Lab is built in seven milestones. Each one ends with the app runnable and its checks passing.
Later milestones start only when the earlier ones pass their acceptance checks.

| Milestone | Scope | Status |
|---|---|---|
| 0 | Repository, design, dependency plan | Done |
| 1 | Compose, migrations, schema, storage, readiness | Done |
| 2 | Durable PDF ingestion | Next |
| 3 | Retrieval and first research validation | Not started |
| 4 | Grounded answers with citations | Not started |
| 5 | React workspace | Not started |
| 6 | Evaluation and handoff | Not started |

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
- CI: lint, typecheck, tests, build, API type drift check, Compose validation, and integration tests against a
  pgvector service container.

Verified: fresh database migrates; downgrade and re-upgrade work; 31 integration tests on constraints, migrations
and readiness pass; data in both volumes survived `make down && make up`. See [operations.md](operations.md).

## Milestone 2: durable ingestion

1. `POST /documents`: streamed upload, byte limit, `%PDF-` magic check, SHA-256, duplicate returns the existing
   document (`200`) instead of a new job (`202`).
2. Worker process and its Compose service: claim with `FOR UPDATE SKIP LOCKED`, commit the claim, then heartbeat
   and renew the lease. Each claim gets a new token; writes and activation check it, so a worker that lost its lease
   cannot publish. Readiness also reports whether the embedding model is available.
3. PyMuPDF extraction per physical page, keeping printed page labels separately. Clear errors for encrypted,
   corrupt, empty and image-only PDFs ("OCR required").
4. Conservative header/footer removal with recorded warnings.
5. Tokenizer-aware, page-local chunks under the model's 512-token limit, with spans back to the page text.
6. Batched embeddings, staged index version, validation, then one transaction that switches the active index.
7. Delete and reindex endpoints. Deletion hides the document from search immediately and cancels jobs.

Acceptance: a real PDF reaches `ready`; spans rebuild chunk text; re-upload is idempotent; killed workers
recover; a stale worker cannot activate; a failed reindex leaves the old index searchable; bad PDFs give useful
errors; deletion during ingestion is safe.
Commands: `make download-model`, `make ingest FILE=...`, integration tests.

## Milestone 3: retrieval and first validation

1. Exact cosine search (`<=>`) over active, ready index versions only, with document and year filters and
   deterministic tie-breaks.
2. `POST /retrieval/search` with ranks, distances, similarity (`1 - distance`), and model and chunking config.
3. Lexical baseline (PostgreSQL full-text search) behind the same interface.
4. `research/corpus/manifest.jsonl` and `make corpus-verify` (hashes, licences, access status).
5. `research/evaluation/questions.jsonl` format with gold evidence anchored to file hash, page and quotation.
6. `make evaluate SPLIT=dev` for retrieval metrics: Recall@k, MRR@k, nDCG@k, evidence-span coverage@k.

Acceptance: real embeddings and PostgreSQL search work together; ranking, filters and score direction are
tested; the 20-paper / 25-question target is met or recorded as externally blocked.

## Milestone 4: grounded answers

1. OpenAI-compatible adapter with a documented minimum contract and clear provider errors.
2. Versioned prompt; passages labelled `E1..En` and treated as untrusted evidence.
3. Context budget: instructions, question and output tokens reserved first.
4. Structured claims validated on the server. Unknown evidence IDs fail. One repair attempt, then a clear error.
5. Citations resolved from stored snapshots, never from model output.
6. No usable evidence means abstaining without calling the LLM. Provider outages are `503`, not abstentions.

Acceptance: see the spec. A live smoke test runs only when credentials exist (`pytest -m live`).

## Milestone 5: React workspace

Documents, Research, Retrieval debug and Evaluations views, built on generated API types. Keyboard access,
visible focus, honest empty, loading, error and abstention states. Upload → ready → ask → inspect passage →
open the PDF at the physical page.

## Milestone 6: evaluation and handoff

Frozen dev and test splits, real evaluation artifacts in `artifacts/`, a human review workflow, operations docs
(backup, restore, deletion, worker recovery), and a final run of every command from a fresh clone.

## Out of scope for the MVP

OCR, hybrid retrieval, reranking, HNSW indexes, streaming answers, FIT uploads, activity sync and training
metrics. The [architecture](architecture.md#future-training-module) describes where training analytics would go
later.
