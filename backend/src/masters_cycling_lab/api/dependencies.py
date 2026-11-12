import threading
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from masters_cycling_lab.api.errors import ApiError
from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.ports import Embedder, LanguageModel
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage


# create_app() builds these once per process and keeps them on app.state.
def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def get_storage(request: Request) -> LocalFileStorage:
    storage: LocalFileStorage = request.app.state.storage
    return storage


def get_session(request: Request) -> Iterator[Session]:
    with Session(get_engine(request)) as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
StorageDep = Annotated[LocalFileStorage, Depends(get_storage)]
SessionDep = Annotated[Session, Depends(get_session)]


_embedder_lock = threading.Lock()


def query_embedder(request: Request) -> Embedder:
    """The embedding model, loaded on first use and then kept for the life of the process."""
    state = request.app.state
    if state.embedder is None:
        with _embedder_lock:
            if state.embedder is None:
                # Imported here: torch takes seconds to import, and most requests never need it.
                from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import (
                    ModelNotDownloaded,
                    SentenceTransformerEmbedder,
                )

                try:
                    state.embedder = SentenceTransformerEmbedder(state.settings)
                except ModelNotDownloaded as exc:
                    raise ApiError(503, "EMBEDDING_MODEL_UNAVAILABLE", str(exc)) from exc
    embedder: Embedder = state.embedder
    return embedder


def language_model(request: Request) -> LanguageModel | None:
    """The configured provider client, or None when LLM_BASE_URL or LLM_MODEL is not set."""
    state = request.app.state
    if state.llm is None and state.settings.llm_configured:
        from masters_cycling_lab.infrastructure.llm.openai_compatible import OpenAICompatibleClient

        state.llm = OpenAICompatibleClient(state.settings)
    llm: LanguageModel | None = state.llm
    return llm
