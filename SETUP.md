# Setup

From a fresh clone to asking a question with cited answers. Everything runs on your machine under Docker Compose.
Allow about 20 minutes, most of it the first image build and loading the research corpus.

## 1. Install the requirements

| Tool | Version | Needed for |
|---|---|---|
| Docker with Compose | recent | Running the app |
| GNU Make | any | Every command below |
| Python | 3.12 | Local checks, tests and corpus commands |
| [uv](https://docs.astral.sh/uv/) | 0.13+ | Installing the backend's locked dependencies |
| Node.js | 24 (`nvm use` reads `.nvmrc`) | Frontend checks and the Vite dev server |

Give Docker at least 4 GB of memory. The worker alone is capped at 3 GB.

## 2. Configure

```bash
git clone https://github.com/kchan1028/masters-cycling-lab.git
```

```bash
cd masters-cycling-lab
```

```bash
cp .env.example .env
```

Open `.env` and set your own `POSTGRES_PASSWORD`. Put the same password in `DATABASE_URL`. The other defaults work
as they are; [`.env.example`](.env.example) explains each setting.

```bash
make bootstrap
```

This installs the locked backend and frontend dependencies and checks your Node version. It creates `.env` only if
it's missing and never overwrites it.

## 3. Start the stack

```bash
make up
```

```bash
make migrate
```

```bash
make download-model
```

- `make up` builds the images and waits until every container is healthy. The first build downloads torch and takes a
  few minutes.
- `make migrate` creates the database schema. The API starts without it on purpose; readiness reports it missing.
- `make download-model` fetches the pinned embedding model (about 140 MB) into a Docker volume. It's the only step
  that contacts Hugging Face. Until it finishes, uploaded PDFs stay queued.

Check that everything is ready:

```bash
curl -s http://127.0.0.1:8080/api/v1/health/ready
```

`"status": "ready"` means the database, migrations, `vector` extension and storage are all fine. A `503` names the
check that failed in `details.checks`.

Open http://127.0.0.1:8080.

## 4. Add papers

Upload your own PDFs from the Papers page, or from the command line:

```bash
make ingest FILE=/absolute/path/paper.pdf
```

To load the 20 open-access papers the evaluation uses (about 10 minutes on CPU):

```bash
make corpus-download
```

```bash
make corpus-ingest
```

Searching and reading work from here on, with no language model.

## 5. Connect a language model (optional)

Answers need an OpenAI-compatible `/chat/completions` endpoint. Set these in `.env`:

```
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=the-model-id
LLM_API_KEY=your-key
```

Then apply the change:

```bash
make up
```

When you ask a question, the question and the selected passages are sent to that provider. If the provider runs on
this machine or behind an SSH tunnel, also set `LLM_DOCKER_BASE_URL`; see
[docs/operations.md](docs/operations.md#answer-generation-llm-provider).

## 6. Check it end to end

```bash
make smoke
```

It uploads a one-page test PDF, waits for indexing, searches it, asks a question and deletes it again. Without LLM
settings the answer step is reported as skipped.

## Developing without Docker

Keep the database running with `make up`, then start the API and the Vite dev server on the host in two terminals:

```bash
uv --directory backend run uvicorn masters_cycling_lab.main:create_app --factory --port 8000
```

```bash
npm --prefix frontend run dev
```

Open http://127.0.0.1:5173. API docs are at http://127.0.0.1:8000/api/docs. Tools on the host use `DATABASE_URL`
(port `5433`) and `MODEL_CACHE_DIR`; run `make model-host` once to download the model there.

Before opening a pull request, run the same checks CI runs:

```bash
make lint
```

```bash
make typecheck
```

```bash
make test
```

```bash
make check-api-types
```

## Stopping and resetting

`make down` stops the stack. Your papers, index and answers stay in Docker volumes and come back with `make up`.
[docs/operations.md](docs/operations.md) covers backups, resets and deleting data.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Set POSTGRES_PASSWORD in .env` | `.env` is missing or the password is empty. Run `cp .env.example .env` and set it |
| `Node 24 or newer is required` | Run `nvm use` in the repository, then `make bootstrap` again |
| Readiness says "run make migrate" | Run `make migrate` |
| Papers stay queued; worker logs "Run `make download-model`" | Run `make download-model` |
| `Error 137` | Docker ran out of memory. Stop other containers or give Docker more memory, then retry |
| Port 8080 or 5433 already in use | Stop the other program, or change the host side of the port in `compose.yaml` (keep `127.0.0.1:`) |
| `HOST_NOT_ALLOWED` (400) | Use `127.0.0.1` or `localhost`, or add your host name to `ALLOWED_HOSTS` |
| Answers fail with `503 LLM_NOT_CONFIGURED` | Set `LLM_BASE_URL` and `LLM_MODEL` in `.env`, then `make up` |
| Answers fail with `503 PROVIDER_UNAVAILABLE` | The provider is down or out of quota. Check its status and your key |

More in [docs/operations.md](docs/operations.md#troubleshooting). Security guidance is in [SECURITY.md](SECURITY.md).
