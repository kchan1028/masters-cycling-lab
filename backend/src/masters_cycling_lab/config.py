import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ in a checkout, /app in the Docker image. Alembic's migrations/ live here.
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    # Real environment variables win over .env. In Docker there is no .env file; Compose passes the values.
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    allowed_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    # Host header values the API answers to. Anything else is rejected, which blocks DNS rebinding.
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]

    database_url: str
    # Relative paths are resolved against the repository root.
    storage_root: Path = Path("/data/storage")

    embedding_model_id: str = "BAAI/bge-small-en-v1.5"
    embedding_model_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    embedding_dimension: int = Field(default=384, gt=0)
    embedding_batch_size: int = Field(default=32, gt=0, le=512)
    # Downloaded model files (make download-model). Relative paths are resolved against the repository root.
    model_cache_dir: Path = Path("data/models")

    # Chunk size in model tokens, without the two special tokens the model adds. bge-small reads at most 512.
    chunk_max_tokens: int = Field(default=300, gt=0, le=510)
    chunk_overlap_tokens: int = Field(default=40, ge=0)

    # Any OpenAI-compatible /chat/completions endpoint. Leaving these empty disables answer generation.
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0, le=600)
    # Tries per model call, counting the first. Only timeouts, connection errors and 5xx replies are retried.
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    llm_max_output_tokens: int = Field(default=1024, gt=0)
    llm_context_window_tokens: int = Field(default=8192, gt=0)

    max_upload_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=300, gt=0)

    retrieval_candidate_k: int = Field(default=20, gt=0, le=100)
    retrieval_context_k: int = Field(default=10, gt=0, le=50)  # 6 often left out the gold passage

    worker_poll_seconds: float = Field(default=2.0, gt=0)

    @field_validator("allowed_origins")
    @classmethod
    def no_wildcard_origin(cls, value: list[str]) -> list[str]:
        # The API has no login, so "*" would let any website you visit read its responses.
        if "*" in value:
            raise ValueError('"*" is not allowed; list the exact origins')
        return value

    @field_validator("storage_root", "model_cache_dir")
    @classmethod
    def resolve_relative_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else REPO_ROOT / value

    @field_validator("embedding_model_revision")
    @classmethod
    def revision_is_commit_hash(cls, value: str) -> str:
        # Branch names like "main" move. Only a full commit hash makes embeddings reproducible.
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("must be a full 40-character commit hash, not a branch or tag")
        return value

    @field_validator("llm_base_url")
    @classmethod
    def base_url_is_http(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value.rstrip("/") if value else None

    @model_validator(mode="after")
    def check_limits(self) -> Self:
        if self.retrieval_context_k > self.retrieval_candidate_k:
            raise ValueError("RETRIEVAL_CONTEXT_K cannot be larger than RETRIEVAL_CANDIDATE_K")
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_MAX_TOKENS")
        if self.llm_max_output_tokens >= self.llm_context_window_tokens:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS must leave room in LLM_CONTEXT_WINDOW_TOKENS for the prompt")
        return self

    @property
    def llm_configured(self) -> bool:
        """True when generation settings are present. It does not mean the provider is reachable."""
        return bool(self.llm_base_url and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
