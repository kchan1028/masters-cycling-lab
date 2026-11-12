"""Client for any OpenAI-compatible /chat/completions endpoint.

The contract we rely on is deliberately small, so most providers work: POST {base_url}/chat/completions with
`model`, `messages`, `temperature` and `max_tokens`, and read `choices[0].message.content`. We do not depend on JSON
mode, tool calling or token usage; the prompt asks for JSON and the answer service validates it, and usage is
recorded only when the provider sends it. No tools are offered to the model, so document text cannot trigger any.
"""

import httpx

from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.ports import LanguageModelReply, ProviderError


class OpenAICompatibleClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.llm_base_url or not settings.llm_model:
            raise ProviderError("LLM_BASE_URL and LLM_MODEL are not set.")
        self.model = settings.llm_model
        self.url = f"{settings.llm_base_url}/chat/completions"
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.timeout = settings.llm_timeout_seconds

    def complete(self, messages: list[dict[str, str]], max_tokens: int) -> LanguageModelReply:
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        try:
            response = httpx.post(self.url, json=body, headers=self.headers, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"The provider did not answer within {self.timeout:g} seconds.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach the provider ({type(exc).__name__}).") from exc
        if response.status_code != 200:
            # The body can echo the request, so only the status goes into the message.
            raise ProviderError(f"The provider returned HTTP {response.status_code}.")
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The provider's reply was not in the chat-completions format.") from exc
        if not isinstance(text, str):
            raise ProviderError("The provider's reply had no text content.")
        usage = data.get("usage")
        reported = {k: v for k, v in usage.items() if isinstance(v, int)} if isinstance(usage, dict) else None
        return LanguageModelReply(text=text, model=str(data.get("model") or self.model), usage=reported or None)
