# API and migration image. Build from the repository root: docker compose build.
FROM python:3.12.16-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so code changes don't reinstall torch.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

RUN useradd --uid 10001 --no-create-home app \
    && mkdir -p /data/storage /data/models \
    && chown app /data/storage /data/models
USER app

EXPOSE 8000
CMD ["uvicorn", "masters_cycling_lab.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
