# Architecture

A modular monolith: one Python package, run as two processes (API and worker), plus PostgreSQL and a static
React frontend. Nothing else. No queue broker, no separate vector database, no RAG framework.

```
browser ── frontend (static build) ──/api──► api (FastAPI)  ──► PostgreSQL + pgvector
                                                │                      ▲
                                                ▼                      │
                                       local file storage ◄── worker (ingestion jobs)
                                                                       │
                                     LLM provider (OpenAI-compatible) ◄┘ only from the api, only for answers
```

## Processes

| Process | Runs | Notes |
|---|---|---|
| `db` | PostgreSQL with the `vector` extension | Internal to Compose; published on `127.0.0.1` only for host-side tests |
| `migrate` | `alembic upgrade head`, then exits | The only thing that changes the schema. API and worker never migrate on startup |
| `api` | `uvicorn masters_cycling_lab.main:create_app --factory` | Loads the embedding model once, for query embeddings |
| `worker` | `python -m masters_cycling_lab.worker` | Claims ingestion jobs from PostgreSQL. Loads the model once |
| `frontend` | nginx serving the Vite build | Proxies `/api` so the browser sees one origin |

Compose arrives in milestone 1. Until then the API runs with `uv run` and the frontend with `npm run dev`.

## Code layout and dependency direction

```
api/routes  →  application  →  domain
                    ↑
             infrastructure (db, storage, pdf, embeddings, llm)
```

- `api/`: HTTP only. Pydantic request/response models, error envelope, dependencies. No SQL, no business rules.
- `application/`: one module per use case (documents, ingestion, retrieval, answering, evaluation). Orchestrates
  the work and owns transaction boundaries.
- `domain/`: plain dataclasses and rules (chunk spans, evidence IDs, citation validation, metrics). Imports
  nothing from FastAPI, SQLAlchemy or PyMuPDF.
- `infrastructure/`: the code that talks to PostgreSQL, the file system, PyMuPDF, sentence-transformers and the
  LLM provider.
- `domain/ports.py` gets a `Protocol` only where there are two real implementations, or where a test double
  replaces something slow or paid (the embedder, the LLM client, the PDF extractor). Database access uses
  SQLAlchemy sessions directly, with no generic repository layer.

Directories are added when the first file that needs them is written. Milestone 0 has only `config.py`,
`main.py`, `cli.py` and `api/`.

## Sessions and blocking work

Synchronous SQLAlchemy 2 with psycopg 3. Route handlers that touch the database, PDF extraction, embeddings or
the provider are plain `def` functions, so FastAPI runs them in its thread pool and the event loop is never
blocked. The worker is a plain loop. It never holds a transaction open during extraction, embedding or model
inference.

## Ingestion and index versions

Every successful ingestion produces a new `index_versions` row. The document points to exactly one active
version. A reindex builds a new version next to the old one; the old one stays searchable until the new one is
validated, and then one transaction switches the pointer. Retrieval reads only active, `ready` versions, so
partial embeddings are never visible.

Job claims are leases with a per-claim token. Every staged write and the final activation check the token in the
same statement, so a worker that lost its lease (slow, paused, killed) cannot publish. Details in
[decisions/0003](decisions/0003-postgres-job-queue-and-index-versions.md).

## Evidence and citations

The answer flow assigns request-local IDs (`E1`, `E2`, ...) to the passages it sends to the model, and stores a
snapshot of each passage and its source metadata in `query_evidence`. The model returns claims that reference
those IDs. The server rejects unknown IDs and builds every citation (title, pages, excerpt, file link) from the
stored snapshot, never from model text. Valid citations are a structural check, not proof that the passage
supports the claim. Support is judged separately during evaluation.

## Security boundaries

- Local, single-user. No authentication, so it must not be exposed beyond `127.0.0.1`. Shared or remote use
  needs authentication and authorization first.
- CORS is limited to `ALLOWED_ORIGINS` and is only for the Vite dev server. It is not access control.
  Milestone 1 adds an `Origin` check on mutating requests.
- Uploaded files get generated storage keys. Filenames are metadata, never paths. No server-side URL fetching.
- Document text is untrusted input to the LLM and is escaped when rendered in the browser.
- Provider keys stay on the server. Questions and selected passages are sent to the configured LLM provider when
  you ask for an answer; nothing else leaves the machine.
- Logs do not include full questions, document text or provider payloads by default. Validation errors leave out
  submitted values.

## Future training module

Not built in the MVP. If added, it lives in its own `training/` package with its own tables:

- athlete profile, consent and preferences
- activity imports with source and file provenance
- power, heart rate, cadence and GPS time series (relational or time-series tables, never embeddings)
- FTP history and zones with effective dates
- workout summaries with versioned metric formulas, units and input provenance

A future coaching service could combine a training summary with research retrieval. The research side must not
import from `training/`, and answers must keep three things visibly separate: research evidence, computed
athlete facts and coaching inference.
