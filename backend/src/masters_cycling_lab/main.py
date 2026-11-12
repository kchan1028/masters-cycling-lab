import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from masters_cycling_lab.api.errors import ErrorResponse, install_error_handlers
from masters_cycling_lab.api.request_checks import rejected_request
from masters_cycling_lab.api.routes import health
from masters_cycling_lab.config import Settings, get_settings
from masters_cycling_lab.infrastructure.db.models import EMBEDDING_DIMENSION
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage


def check_embedding_dimension(settings: Settings) -> None:
    if settings.embedding_dimension != EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"EMBEDDING_DIMENSION is {settings.embedding_dimension} but the database column is "
            f"vector({EMBEDDING_DIMENSION}). A different dimension needs a migration and a full reindex."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    check_embedding_dimension(settings)

    app = FastAPI(
        title="Masters Cycling Lab API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.storage = LocalFileStorage(settings.storage_root)

    # CORS only matters for a dev frontend on another origin. It is not access control.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def check_and_tag_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = str(uuid.uuid4())
        response: Response | None = rejected_request(request, settings)
        if response is None:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    install_error_handlers(app)

    error_responses: dict[int | str, dict[str, object]] = {"default": {"model": ErrorResponse}}
    app.include_router(health.router, prefix="/api/v1", responses=error_responses)
    return app
