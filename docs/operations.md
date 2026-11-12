# Operations

How to run, check and reset the local stack. Everything here is for one person on one machine.

## Services and ports

| Service | Reachable at | Notes |
|---|---|---|
| `frontend` | http://127.0.0.1:8080 | nginx: serves the React build and proxies `/api` to the API |
| `api` | inside Docker only (`api:8000`) | Use it through http://127.0.0.1:8080/api/... |
| `db` | `127.0.0.1:5433` | Published on loopback for integration tests and `psql`. Remove the `ports` entry in `compose.yaml` if you don't need it |
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

`make up` builds the images and waits until the containers are healthy. The first build downloads torch and takes a few
minutes. The API starts without migrations on purpose; readiness tells you when it's missing them.

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

## Stopping and data

```bash
make down
```

Data lives in two Docker volumes and survives `make down`, `make up` and image rebuilds:

- `masters-cycling-lab_pgdata`: PostgreSQL
- `masters-cycling-lab_storage`: uploaded PDFs

`docker compose down --volumes` deletes both permanently. Backup and restore steps arrive in milestone 6, once there
is real data worth keeping; until then treat the local database as disposable.

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

`make test` needs nothing running. `make test-integration` needs the `db` container. It creates throwaway databases
named `mcl_test_*` next to your real one and drops them when it finishes, so it never touches your data.

## Troubleshooting

- **Port 8080 or 5433 already in use.** Stop the other program or change the host side of the port in
  `compose.yaml`.
- **`HOST_NOT_ALLOWED` (400).** The request used a host name that isn't in `ALLOWED_HOSTS`. Use `127.0.0.1` or
  `localhost`, or add the name you need.
- **`ORIGIN_NOT_ALLOWED` (403).** A browser on another origin tried to change data. Add that origin to
  `ALLOWED_ORIGINS` only if it is your own dev server.
