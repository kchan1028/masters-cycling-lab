# Masters Cycling Lab

A local research workspace for evidence relevant to masters cyclists: upload research PDFs, search them,
ask questions and get answers whose citations point to the exact passage and PDF page they came from. It is also
a hands-on project for learning how retrieval-augmented generation works, with every step inspectable.

It uses pretrained models only. It does not give personal training or medical advice.

**Status: milestone 2 of 6 done.** PDFs can be uploaded, extracted, chunked and embedded by a durable worker, with
every chunk traceable to its page. Search and answers are not built yet. See [docs/roadmap.md](docs/roadmap.md).

## Requirements

- Docker with Compose
- Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13+ (for local checks and tests)
- Node.js 24 (`nvm use` reads `.nvmrc`)
- GNU Make

## Setup

```bash
cp .env.example .env
```

Set your own `POSTGRES_PASSWORD` in `.env` and use the same password in `DATABASE_URL`.

```bash
make bootstrap
```

`make bootstrap` installs the locked backend and frontend dependencies for local checks. It creates `.env` from
`.env.example` only if `.env` does not exist; it never overwrites it.

## Run it

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
make ingest FILE=/absolute/path/paper.pdf
```

Open http://127.0.0.1:8080. Check readiness at http://127.0.0.1:8080/api/v1/health/ready.
[docs/operations.md](docs/operations.md) covers ports, volumes, resets and troubleshooting.

For frontend or API development without Docker, run the database with `make up`, then the API and the Vite dev
server on the host in two terminals:

```bash
uv --directory backend run uvicorn masters_cycling_lab.main:create_app --factory --port 8000
```

```bash
npm --prefix frontend run dev
```

Open http://127.0.0.1:5173. API docs are at http://127.0.0.1:8000/api/docs.

## Commands

| Command | What it does | Available |
|---|---|---|
| `make bootstrap` | Install locked dependencies | now |
| `make lint` | Ruff and ESLint | now |
| `make typecheck` | mypy and tsc | now |
| `make test` | Fast offline tests (no database, model download or LLM) | now |
| `make test-integration` | Tests against PostgreSQL in throwaway databases (needs `make up`) | now |
| `make test-model` | Tests with the real embedding model (downloads it on first use) | now |
| `make build` | Production frontend bundle | now |
| `make api-types` | Regenerate `backend/openapi.json` and the frontend's TypeScript types | now |
| `make check-api-types` | Fail if those generated files are out of date | now |
| `make up` / `make down` | Start / stop the Compose stack; data stays in Docker volumes | now |
| `make migrate` | Apply database migrations (the only thing that changes the schema) | now |
| `make download-model` | Download the pinned embedding model into the Docker volume | now |
| `make ingest FILE=/abs/path.pdf` | Upload one PDF and wait for the worker | now |
| `make corpus-download` | Fetch the 20 corpus PDFs from PMC Open Access (checked by SHA-256) | now |
| `make corpus-verify` | Check corpus PDFs against the manifest and report how many are searchable | now |
| `make corpus-ingest` | Upload the corpus with its manifest metadata and wait for the worker | now |
| `make evaluate SPLIT=dev` | Run the labelled evaluation | milestone 3 |
| `make smoke` | End-to-end check against a running stack | milestone 5 |

Commands that are not implemented yet exit with an error instead of pretending to work.

## Configuration

All settings live in `.env` and are validated when the backend starts. [`.env.example`](.env.example) explains
each one. Things to know:

- **Embedding model.** `BAAI/bge-small-en-v1.5`, pinned to a commit hash. Changing it means re-embedding every
  document ([decision 0002](docs/decisions/0002-embedding-model.md)).
- **LLM provider.** Any OpenAI-compatible `/chat/completions` endpoint. Leave `LLM_BASE_URL` or `LLM_MODEL` empty
  to run without answer generation. When you ask a question, the question and the selected passages are sent to
  that provider. Keys stay on the server and are never sent to the browser.

## Documentation

- [Roadmap](docs/roadmap.md): milestones, acceptance checks, assumptions and blockers
- [Architecture](docs/architecture.md): processes, layers, data model, security boundaries
- [Operations](docs/operations.md): running, checking and resetting the local stack
- [Dependencies and licences](docs/dependencies.md): pinned versions and what the licences mean
- [Decisions](docs/decisions/): why the stack, model, queue and retrieval work the way they do

## Data and licensing

This is a single-user app for your own machine. It has no login, so don't expose it to a network.

Research PDFs are not stored in git. The corpus manifest records where each paper came from and whether it may be
redistributed. PyMuPDF is AGPL-3.0, which matters if you distribute the app or run it for other people; see
[dependencies.md](docs/dependencies.md#licensing-implications). The project itself has no licence yet.
