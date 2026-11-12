import logging
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from masters_cycling_lab.api.dependencies import EngineDep, SettingsDep, StorageDep
from masters_cycling_lab.api.errors import ApiError, ErrorResponse
from masters_cycling_lab.infrastructure.db.migrations import current_revision, head_revision
from masters_cycling_lab.infrastructure.embeddings.model_cache import model_files_present
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

LlmStatus = Literal["configured", "not_configured"]


class LiveStatus(BaseModel):
    status: Literal["ok"]


class ReadyStatus(BaseModel):
    status: Literal["ready"]
    checks: dict[str, str]
    # Whether generation settings are present. It does not mean the provider is reachable.
    llm: LlmStatus


@router.get("/live")
async def live() -> LiveStatus:
    """The API process is running. Says nothing about the database or the embedding model."""
    return LiveStatus(status="ok")


@router.get("/ready", responses={503: {"model": ErrorResponse, "description": "A required dependency is not ready"}})
def ready(request: Request, settings: SettingsDep, engine: EngineDep, storage: StorageDep) -> ReadyStatus:
    """Checks the database, migrations, the vector extension, file storage and the embedding model files.
    Never calls the LLM provider."""
    checks = check_dependencies(engine, storage)
    model_ready = request.app.state.embedder is not None or model_files_present(settings)
    checks["embedding_model"] = "ok" if model_ready else "not downloaded; run make download-model"
    llm: LlmStatus = "configured" if settings.llm_configured else "not_configured"
    if any(result != "ok" for result in checks.values()):
        raise ApiError(503, "NOT_READY", "Some required dependencies are not ready.", {"checks": checks, "llm": llm})
    return ReadyStatus(status="ready", checks=checks, llm=llm)


def check_dependencies(engine: Engine, storage: LocalFileStorage) -> dict[str, str]:
    checks = {"database": "ok", "migrations": "not checked", "vector_extension": "not checked"}
    try:
        with engine.connect() as connection:
            current, head = current_revision(connection), head_revision()
            if current == head:
                checks["migrations"] = "ok"
            else:
                checks["migrations"] = (
                    f"database is at {current or 'no revision'}, code expects {head}; run make migrate"
                )
            vector = connection.execute(text("select 1 from pg_extension where extname = 'vector'")).first()
            checks["vector_extension"] = "ok" if vector else "missing"
    except SQLAlchemyError as exc:
        # The exception text can include the host and user name, so only its type is logged.
        log.warning("Readiness: database check failed (%s)", type(exc).__name__)
        checks["database"] = "unreachable"
    checks["storage"] = "ok" if storage.is_writable() else "not writable"
    return checks
