# Operations

How to run, check and reset the local stack. Everything here is for one person on one machine.

## Services and ports

| Service | Reachable at | Notes |
|---|---|---|
| `frontend` | http://127.0.0.1:8080 | nginx: serves the React build and proxies `/api` to the API |
| `api` | inside Docker only (`api:8000`) | Use it through http://127.0.0.1:8080/api/... |
| `db` | `127.0.0.1:5433` | Published on loopback for integration tests and `psql`. Remove the `ports` entry in `compose.yaml` if you don't need it |
| `worker` | inside Docker only | Extracts, chunks and embeds PDFs. Capped at 3 GB of memory and 2 CPUs |
| `migrate` | one-shot | Runs `alembic upgrade head` and exits. Only started by `make migrate` |

Nothing is published on other network interfaces. The app has no login, so keep it that way.

## First start

```bash
cp .env.example .env
```

Change `POSTGRES_PASSWORD` in `.env`, and use the same password in `DATABASE_URL`.

```bash
make up
```

```bash
make migrate
```

```bash
make download-model
```

`make up` builds the images and waits until the containers are healthy. The first build downloads torch and takes a few
minutes. The API starts without migrations on purpose; readiness tells you when it's missing them.

`make download-model` fetches the pinned embedding model (`BAAI/bge-small-en-v1.5` at a fixed commit, about 140 MB)
into the `models` volume. It is the only step that contacts Hugging Face; the containers run with `HF_HUB_OFFLINE=1`.
Until the model is there, the worker logs "Run `make download-model`" every 30 seconds and leaves jobs queued. It
refuses an incomplete download rather than letting sentence-transformers fall back to a different model.

## Adding documents

Upload through the API (or the UI, from milestone 5):

```bash
curl -F "file=@/absolute/path/paper.pdf" http://127.0.0.1:8080/api/v1/documents
```

or from the command line, which also waits and prints progress:

```bash
make ingest FILE=/absolute/path/paper.pdf
```

- A new file returns `202` with a queued job. The same file again (same SHA-256) returns `200` with
  `"duplicate": true` and the existing document; nothing new is stored or queued.
- `GET /api/v1/ingestion-jobs/{id}` shows the stage (`extracting`, `embedding`, `activating`), progress, attempts and,
  on failure, a stable `error_code` with a readable message.
- Codes that need you to act: `PDF_ENCRYPTED` (remove the password), `OCR_REQUIRED` (scanned PDF; OCR is not
  supported), `PDF_CORRUPT`, `PDF_TOO_MANY_PAGES` (raise `MAX_PDF_PAGES` or split the file).
- `INGESTION_ERROR` means an unexpected error; the job is retried up to 3 times with growing delays. `WORKER_LOST`
  means workers died on it 3 times. `docker compose logs worker` has the details; logs never include document text.
- `POST /api/v1/documents/{id}/ingestions` rebuilds a document's index. The current index stays searchable until the
  new one is ready, and stays if the rebuild fails.
- `DELETE /api/v1/documents/{id}` is permanent: the PDF, its index, and any answer history that quoted it are
  removed. A worker processing the document stops at its next step without publishing anything.
- `GET /api/v1/documents/{id}/pages/{n}` returns the stored text of physical page `n` with its extraction warnings
  (removed headers, pages without text). Check these for important papers.

To load the research corpus, run `make corpus-download`, then `make corpus-ingest` (about 10 minutes for 20 papers on
CPU). Details in [research/corpus/README.md](../research/corpus/README.md).

If a worker is killed mid-job, its lease (5 minutes) expires and the next worker takes the job over; the
half-built index version is discarded.

## Is it working?

```bash
curl -s http://127.0.0.1:8080/api/v1/health/ready
```

- `200` with `"status": "ready"`: database reachable, migrations at head, `vector` extension installed, storage
  writable.
- `503` with `"code": "NOT_READY"`: `details.checks` says which one failed. "run make migrate" means exactly that.
- `llm` is `configured` or `not_configured`. It only reports whether the settings are present. Readiness never calls
  the provider, so it costs nothing and does not prove the provider works.

`/api/v1/health/live` only says the API process is up.

`make smoke` checks the whole stack through the frontend's address: it uploads a one-page synthetic PDF, waits for
the worker, searches it, reads its page text and original file back, asks a question and deletes it again. Without
LLM settings the answer step is reported as skipped (`503 LLM_NOT_CONFIGURED`); any other failure fails the check.
It needs the embedding model (`make download-model`) and takes about a minute, mostly the API loading the model on
its first search.

## Stopping and data

```bash
make down
```

Data lives in two Docker volumes and survives `make down`, `make up` and image rebuilds:

- `masters-cycling-lab_pgdata`: PostgreSQL
- `masters-cycling-lab_storage`: uploaded PDFs
- `masters-cycling-lab_models`: the downloaded embedding model

`docker compose down --volumes` deletes all three permanently.

## Backup and restore

```bash
make backup
```

With the stack running, this writes `backups/<UTC time>/` (git-ignored): `database.dump` (`pg_dump` custom format:
documents, index versions, chunks and embeddings, answers, evaluation runs), `storage.tar` (the uploaded PDFs) and
`SHA256SUMS`. It reads both parts back before it reports success. The embedding model is not included;
`make download-model` fetches it again. The two parts are copied one after the other, so take a backup while
nothing is being uploaded or deleted. Copy the folder somewhere off this machine to make it a real backup.

```bash
make restore BACKUP=backups/20261112T174634Z
```

Restore replaces everything: it checks the hashes, asks you to type `restore`, stops the API and worker, drops and
recreates the database, loads the dump, replaces the stored PDFs and starts the API and worker again. If it fails
part way, run it again with the same backup. To move to a new machine: clone, set up `.env`, `make up`,
`make download-model`, then `make restore` (no `make migrate` needed; the dump includes the schema at its version).

Verified on 2026-11-12 in a separate Compose project: backup of the 20-paper corpus, delete a document, restore,
and the document, its file (same SHA-256), every gold quotation and the evaluation metrics were back. The restored
API container gets a new address; nginx looks it up again within 10 seconds, so the page may show errors briefly.

## Deleting a document

`DELETE /api/v1/documents/{id}` (or Delete on the Documents page) is permanent and hides the document at once: its
PDF, index versions, pages, chunks and embeddings, and every stored answer that quoted it are removed. Not removed:
evaluation runs (in the database and in `artifacts/evaluations/`) keep up to 300 characters of each passage they
returned, so a deleted paper's excerpts stay in older runs; and backups made before the deletion still contain it.

## Schema changes

Only `make migrate` changes the schema, and it runs exactly one migration process. To add a migration after
changing `backend/src/masters_cycling_lab/infrastructure/db/models.py`:

```bash
uv --directory backend run alembic revision --autogenerate -m "describe the change"
```

Read the generated file before committing it. Autogenerate misses some things (for example foreign keys between
two tables that reference each other) and `tests/integration/test_migrations.py` fails if the models and migrations
disagree.

## Tests

```bash
make test
```

```bash
make test-integration
```

```bash
make test-model
```

`make test` needs nothing running. `make test-integration` needs the `db` container. It creates throwaway databases
named `mcl_test_*` next to your real one and drops them when it finishes, so it never touches your data.
`make test-model` loads the real embedding model (downloading it into `data/models/` on first use) and runs the
tests that depend on its tokenizer and vectors.

## Troubleshooting

- **A command ends with `Error 137`.** Docker killed the container for memory. The worker is capped at 3 GB, and
  the whole Docker VM may be short if other projects' containers are running. Stop what you don't need (or give
  Docker more memory) and run the command again. The same pressure can kill the worker mid-job: jobs are retried, and
  a document that still ends in `WORKER_LOST` only needs Reindex once memory is free. On 2026-11-12, with other
  projects' containers filling the Docker VM, 18 of 20 corpus papers recovered on their own and 2 needed a reindex.
- **Port 8080 or 5433 already in use.** Stop the other program or change the host side of the port in
  `compose.yaml`.
- **`HOST_NOT_ALLOWED` (400).** The request used a host name that isn't in `ALLOWED_HOSTS`. Use `127.0.0.1` or
  `localhost`, or add the name you need.
- **`ORIGIN_NOT_ALLOWED` (403).** A browser on another origin tried to change data. Add that origin to
  `ALLOWED_ORIGINS` only if it is your own dev server.
