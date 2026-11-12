SHELL := /bin/bash
UV := uv --directory backend
NPM := npm --prefix frontend
COMPOSE := docker compose

.PHONY: help bootstrap lint typecheck test test-integration test-model build api-types check-api-types \
	up down migrate download-model ingest corpus-download corpus-verify corpus-ingest model-host labels-check evaluate smoke

help: ## List commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

bootstrap: ## Install locked backend and frontend dependencies (creates .env only if missing)
	@test -f .env || { cp .env.example .env && echo "Created .env from .env.example. Review it before 'make up'."; }
	@node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 24 ? 0 : 1)' \
		|| { echo "Node 24 or newer is required (see .nvmrc, then run 'nvm use')."; exit 1; }
	$(UV) sync --locked
	$(NPM) ci

lint: ## Ruff and ESLint
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(NPM) run lint

typecheck: ## mypy and tsc
	$(UV) run mypy src tests
	$(NPM) run typecheck

test: ## Fast offline tests: no database, model download or LLM provider
	$(UV) run pytest -m "not integration and not model and not live"
	$(NPM) test

test-integration: ## Tests against real PostgreSQL in throwaway databases (needs 'make up')
	$(UV) run pytest -m "integration and not model"

test-model: ## Tests that load the real embedding model (downloads it to data/models on first run)
	$(UV) run pytest -m model

build: ## Production frontend bundle
	$(NPM) run build

api-types: ## Regenerate backend/openapi.json and the frontend's TypeScript types from it
	$(UV) run mcl openapi openapi.json
	$(NPM) run api-types

check-api-types: api-types ## Fail if the committed OpenAPI file or frontend types are out of date
	git diff --exit-code -- backend/openapi.json frontend/src/api/generated

up: ## Build and start the stack: http://127.0.0.1:8080 (run 'make migrate' after the first start)
	$(COMPOSE) up --detach --build --wait

down: ## Stop the stack. Data stays in the Docker volumes
	$(COMPOSE) down

migrate: ## Apply database migrations (the only command that changes the schema)
	$(COMPOSE) run --rm migrate

download-model: ## Download the pinned embedding model into the models volume (about 130 MB, once)
	$(COMPOSE) run --rm --no-deps -e HF_HUB_OFFLINE=0 worker mcl download-model

ingest: ## Upload one PDF and wait for the worker: make ingest FILE=/absolute/path/paper.pdf
	@case "$(FILE)" in /*) ;; *) echo "Usage: make ingest FILE=/absolute/path/paper.pdf" >&2; exit 1;; esac
	@test -f "$(FILE)" || { echo "No such file: $(FILE)" >&2; exit 1; }
	$(COMPOSE) run --rm --no-deps -v "$(FILE):/tmp/upload.pdf:ro" worker \
		mcl ingest /tmp/upload.pdf --filename "$$(basename "$(FILE)")" --wait

corpus-download: ## Fetch the corpus PDFs listed in research/corpus/manifest.jsonl (checked by SHA-256)
	$(UV) run mcl corpus download

corpus-verify: ## Check every corpus PDF against the manifest, and report ingestion status if the database is up
	$(UV) run mcl corpus verify --check-index

corpus-ingest: ## Upload the corpus PDFs with their manifest metadata and wait for the worker
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR)/research/corpus:/corpus:ro" worker \
		mcl corpus ingest --manifest /corpus/manifest.jsonl --wait

model-host: ## Download the pinned embedding model into data/models for commands run on the host
	$(UV) run mcl download-model

labels-check: ## Check every gold quotation in research/evaluation/questions.jsonl against the stored pages
	$(UV) run mcl evaluate --check-labels

evaluate: model-host ## Retrieval evaluation, vector and lexical: make evaluate SPLIT=dev (or SPLIT=test)
	$(UV) run mcl evaluate --split $(or $(SPLIT),dev)

# Commands from the roadmap that later milestones implement. They fail loudly until then.
smoke:
	@echo "'make $@' is not implemented yet. docs/roadmap.md lists the milestone that adds it." >&2; exit 1
