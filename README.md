# Masters Cycling Lab

A local research workspace for evidence relevant to masters cyclists: upload research PDFs, search them,
ask questions and get answers whose citations point to the exact passage and PDF page they came from. It is also
a hands-on project for learning how retrieval-augmented generation works, with every step inspectable.

It uses pretrained models only. It does not give personal training or medical advice.

**Status: MVP complete, with two open blockers.** Upload papers, search them, ask questions and check every citation
against the PDF page in the browser. Not done yet: no LLM provider has been tested (no credentials), so answers return
`503` until one is configured; and none of the evaluation labels has been reviewed by a person. The
[handoff](docs/handoff.md) lists what works, what was verified, the results and the next steps.

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

Add your own PDFs from the Papers page or with `make ingest FILE=/absolute/path/paper.pdf`. To load the 20-paper
open-access research corpus the evaluation uses (about 10 minutes on CPU):

```bash
make corpus-download
```

```bash
make corpus-ingest
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

| Command | What it does |
|---|---|
| `make bootstrap` | Install locked dependencies |
| `make lint` | Ruff and ESLint |
| `make typecheck` | mypy and tsc |
| `make test` | Fast offline tests (no database, model download or LLM) |
| `make test-integration` | Tests against PostgreSQL in throwaway databases (needs `make up`) |
| `make test-model` | Tests with the real embedding model (downloads it on first use) |
| `make build` | Production frontend bundle |
| `make api-types` | Regenerate `backend/openapi.json` and the frontend's TypeScript types |
| `make check-api-types` | Fail if those generated files are out of date |
| `make up` / `make down` | Start / stop the Compose stack; data stays in Docker volumes |
| `make migrate` | Apply database migrations (the only thing that changes the schema) |
| `make download-model` | Download the pinned embedding model into the Docker volume |
| `make ingest FILE=/abs/path.pdf` | Upload one PDF and wait for the worker |
| `make corpus-download` | Fetch the 20 corpus PDFs from PMC Open Access (checked by SHA-256) |
| `make corpus-verify` | Check corpus PDFs against the manifest and report how many are searchable |
| `make corpus-ingest` | Upload the corpus with its manifest metadata and wait for the worker |
| `make labels-check` | Check every gold quotation against the stored page text |
| `make review REVIEWER="Your Name"` | Review provisional labels against the papers and record the verdict |
| `make evaluate SPLIT=dev` | Retrieval evaluation (vector, lexical and hybrid) with a stored artifact; `SPLIT=test2` for the fresh held-out split, from a clean checkout |
| `make test-live` | Opt-in: answer tests against the configured LLM provider (costs money) |
| `make backup` / `make restore BACKUP=backups/<time>` | Copy the database and PDFs out; replace all data from a copy |
| `make smoke` | End-to-end check against the running stack: upload, index, search, page, file, answer, delete |

## Configuration

All settings live in `.env` and are validated when the backend starts. [`.env.example`](.env.example) explains
each one. Things to know:

- **Embedding model.** `BAAI/bge-small-en-v1.5`, pinned to a commit hash. Changing it means re-embedding every
  document ([decision 0002](docs/decisions/0002-embedding-model.md)).
- **LLM provider.** Any OpenAI-compatible `/chat/completions` endpoint. Leave `LLM_BASE_URL` or `LLM_MODEL` empty
  to run without answer generation. When you ask a question, the question and the selected passages are sent to
  that provider. Keys stay on the server and are never sent to the browser.

## Documentation

- [Plain-English overview](docs/overview.html): what the app does, how it answers and how well it works, without jargon
- [Handoff](docs/handoff.md): what works, what was verified, results, open blockers and next steps
- [Roadmap](docs/roadmap.md): milestones, acceptance checks, assumptions and blockers
- [Architecture](docs/architecture.md): processes, layers, data model, security boundaries
- [Operations](docs/operations.md): running, checking and resetting the local stack
- [Evaluation](docs/evaluation.md): metrics, targets and results
- [Dependencies and licences](docs/dependencies.md): pinned versions and what the licences mean
- [Decisions](docs/decisions/): why the stack, model, queue and retrieval work the way they do

## Data and licensing

This is a single-user app for your own machine. It has no login, so don't expose it to a network.

Research PDFs are not stored in git. The corpus manifest records where each paper came from and whether it may be
redistributed. PyMuPDF is AGPL-3.0, which matters if you distribute the app or run it for other people; see
[dependencies.md](docs/dependencies.md#licensing-implications). The project itself has no licence yet.
