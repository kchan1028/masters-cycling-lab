SHELL := /bin/bash
UV := uv --directory backend
NPM := npm --prefix frontend

.PHONY: help bootstrap lint typecheck test build api-types \
	up down migrate download-model ingest corpus-verify evaluate smoke

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

build: ## Production frontend bundle
	$(NPM) run build

api-types: ## Regenerate backend/openapi.json and the frontend's TypeScript types from it
	$(UV) run mcl openapi openapi.json
	$(NPM) run api-types

# Commands from the roadmap that later milestones implement. They fail loudly until then.
up down migrate download-model ingest corpus-verify evaluate smoke:
	@echo "'make $@' is not implemented yet. docs/roadmap.md lists the milestone that adds it." >&2; exit 1
