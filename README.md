# Masters Cycling Lab

A local research workspace for evidence relevant to masters cyclists: upload research PDFs, search them,
ask questions and get answers whose citations point to the exact passage and PDF page they came from. It is also
a hands-on project for learning how retrieval-augmented generation works, with every step inspectable.

It uses pretrained models only. It does not give personal training or medical advice.

**Status: milestone 0 of 6.** The backend and frontend skeletons, configuration and dependency plan are in place.
Uploading, search and answers are not built yet. See [docs/roadmap.md](docs/roadmap.md).

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13+
- Node.js 24 (`nvm use` reads `.nvmrc`)
- Docker with Compose (from milestone 1)
- GNU Make

## Setup

```bash
cp .env.example .env
```

```bash
make bootstrap
```

`make bootstrap` installs the locked backend and frontend dependencies. It creates `.env` from `.env.example`
only if `.env` does not exist; it never overwrites it.

Run the API and the frontend dev server in two terminals:

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
| `make build` | Production frontend bundle | now |
| `make api-types` | Regenerate `backend/openapi.json` and the frontend's TypeScript types | now |
| `make up` / `make down` | Start / stop the Compose stack | milestone 1 |
| `make migrate` | Apply database migrations | milestone 1 |
| `make download-model` | Download the pinned embedding model | milestone 2 |
| `make ingest FILE=/abs/path.pdf` | Ingest one PDF from the command line | milestone 2 |
| `make corpus-verify` | Check the corpus manifest against stored files | milestone 3 |
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
- [Architecture](docs/architecture.md): processes, layers, data flow, security boundaries
- [Dependencies and licences](docs/dependencies.md): pinned versions and what the licences mean
- [Decisions](docs/decisions/): why the stack, model, queue and retrieval work the way they do

## Data and licensing

This is a single-user app for your own machine. It has no login, so don't expose it to a network.

Research PDFs are not stored in git. The corpus manifest records where each paper came from and whether it may be
redistributed. PyMuPDF is AGPL-3.0, which matters if you distribute the app or run it for other people; see
[dependencies.md](docs/dependencies.md#licensing-implications). The project itself has no licence yet.
