"""Calls the real configured provider. Opt-in (`make test-live`) because it costs money and needs credentials."""

import pytest

from masters_cycling_lab.config import get_settings
from masters_cycling_lab.domain.answers import parse_answer
from masters_cycling_lab.infrastructure.llm.openai_compatible import OpenAICompatibleClient

pytestmark = pytest.mark.live


def test_the_configured_provider_follows_the_answer_contract() -> None:
    settings = get_settings()
    if not settings.llm_configured:
        pytest.skip("LLM_BASE_URL and LLM_MODEL are not set")
    llm = OpenAICompatibleClient(settings)
    messages = [
        {
            "role": "system",
            "content": 'Reply only with {"status": "answered", "claims": [{"text": "Masters cyclists '
            'took part.", "evidence_ids": ["E1"]}], "limitations": []}',
        },  # fmt: skip
        {"role": "user", "content": "Go."},
    ]
    # The configured budget, not a small fixed one: reasoning models spend part of it before they write the answer.
    draft = parse_answer(llm.complete(messages, settings.llm_max_output_tokens).text, {"E1"})
    assert draft.status == "answered"
