# 0001: Stack and code structure

Date: 2026-11-12. Status: accepted.

## Context

The app is a learning project for RAG engineering and a research tool, run by one person on one machine. It has
to be easy to read, easy to debug and honest about what it does. The spec fixes the main stack: FastAPI,
PostgreSQL with pgvector, SQLAlchemy 2, Alembic, PyMuPDF, sentence-transformers, React with Vite and TypeScript.

## Decision

- **One Python package, two processes.** The API and the ingestion worker share code and run as separate
  processes. No Celery, no Redis: PostgreSQL is the queue (see 0003).
- **No RAG framework.** Chunking, retrieval, prompt building and citation checks are small and are the parts
  worth learning and inspecting. LangChain or LlamaIndex would hide them.
- **Layers:** `api → application → domain`, with `infrastructure` holding the adapters. Protocols only where a
  second implementation or a test double is real (embedder, LLM client, PDF extractor). No generic repository
  classes; application services use SQLAlchemy sessions directly.
- **Synchronous SQLAlchemy** with psycopg 3. Blocking routes are `def`, so FastAPI runs them in a thread pool.
  One session model everywhere is simpler than mixing sync and async.
- **uv** for Python dependencies (`uv.lock`), **npm** for the frontend (`package-lock.json`).
- **OpenAPI is the contract.** `backend/openapi.json` is committed and checked by a test; the frontend's types
  are generated from it with `openapi-typescript`. Hand-written TypeScript copies of API shapes are not allowed.
- **Conventions carried over from the author's other projects** (`job-search`): `pydantic-settings` with a cached
  `get_settings()`, Alembic `env.py` reading those settings, Ruff with 120-character lines, Compose ports bound
  to `127.0.0.1`, `pg_isready` health checks, non-root containers. Unlike `job-search`, migrations run in their
  own one-shot service instead of on API startup, so two processes never race to migrate.

## Consequences

- Fewer moving parts and dependencies. Everything that matters for retrieval quality is our own code and visible
  in the debug output.
- We write a little more code ourselves (the job queue, the prompt builder) and own its tests.
- Moving to async later would touch every database call. That is acceptable at this scale.
