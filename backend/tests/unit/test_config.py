from typing import Any

import pytest
from pydantic import ValidationError

from masters_cycling_lab.config import Settings


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"database_url": "postgresql+psycopg://test@localhost/test"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_defaults_are_valid() -> None:
    settings = make_settings()
    assert settings.embedding_dimension == 384
    assert settings.retrieval_context_k <= settings.retrieval_candidate_k
    assert not settings.llm_configured


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


@pytest.mark.parametrize("revision", ["main", "v1.5", "5c38ec7"])
def test_embedding_revision_must_be_a_full_commit_hash(revision: str) -> None:
    with pytest.raises(ValidationError, match="commit hash"):
        make_settings(embedding_model_revision=revision)


def test_context_k_cannot_exceed_candidate_k() -> None:
    with pytest.raises(ValidationError, match="RETRIEVAL_CONTEXT_K"):
        make_settings(retrieval_candidate_k=5, retrieval_context_k=6)


def test_output_tokens_must_leave_room_for_the_prompt() -> None:
    with pytest.raises(ValidationError, match="LLM_MAX_OUTPUT_TOKENS"):
        make_settings(llm_max_output_tokens=4096, llm_context_window_tokens=4096)


def test_llm_base_url_is_normalized() -> None:
    settings = make_settings(llm_base_url="https://api.example.com/v1/", llm_model="some-model")
    assert settings.llm_base_url == "https://api.example.com/v1"
    assert settings.llm_configured


def test_llm_base_url_must_be_http() -> None:
    with pytest.raises(ValidationError, match="http"):
        make_settings(llm_base_url="file:///etc/passwd")


def test_api_key_is_not_shown_in_repr() -> None:
    settings = make_settings(llm_api_key="sk-not-a-real-key")
    assert "sk-not-a-real-key" not in repr(settings)
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "sk-not-a-real-key"


def test_allowed_origins_parse_from_json_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", '["http://127.0.0.1:8080"]')
    assert make_settings().allowed_origins == ["http://127.0.0.1:8080"]
