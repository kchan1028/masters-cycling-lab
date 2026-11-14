"""Client for any OpenAI-compatible /chat/completions endpoint.

The contract we rely on is deliberately small, so most providers work: POST {base_url}/chat/completions with
`model`, `messages`, `temperature` and `max_tokens`, and read `choices[0].message.content`. We do not depend on JSON
mode, tool calling or token usage; the prompt asks for JSON and the answer service validates it, and usage is
recorded only when the provider sends it. No tools are offered to the model, so document text cannot trigger any.

Timeouts, connection errors and 5xx replies are retried up to LLM_MAX_ATTEMPTS with a short fixed pause. Anything
else (4xx, a malformed reply) fails at once, because sending the same request again would get the same answer.
"""

import time

import httpx

from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.ports import LanguageModelReply, ProviderError

RETRY_PAUSE_SECONDS = 1.0


class _Transient(ProviderError):
    """A failure worth one more try: timeout, connection error or 5xx."""


class OpenAICompatibleClient:
    """Calls the configured model at temperature 0. Raises ProviderError if it isn't configured."""

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_base_url or not settings.llm_model:
            raise ProviderError("LLM_BASE_URL and LLM_MODEL are not set.")
        self.model = settings.llm_model
        self.url = f"{settings.llm_base_url}/chat/completions"
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.timeout = settings.llm_timeout_seconds
        self.max_attempts = settings.llm_max_attempts

    def complete(self, messages: list[dict[str, str]], max_tokens: int) -> LanguageModelReply:
        """Send the messages and return the reply text. Raises ProviderError.

        Timeouts, network errors, non-200 statuses and replies without text all become ProviderError. The first three
        are retried (5xx only, not 4xx) up to max_attempts. Messages carry only the status, never the response body,
        because a body can echo the request. The reply's usage includes `provider_attempts`.
        """
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._post(body)
                break
            except _Transient:
                if attempt == self.max_attempts:
                    raise
                time.sleep(RETRY_PAUSE_SECONDS)
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The provider's reply was not in the chat-completions format.") from exc
        if not isinstance(text, str):
            raise ProviderError("The provider's reply had no text content.")
        usage = data.get("usage")
        reported = {k: v for k, v in usage.items() if isinstance(v, int)} if isinstance(usage, dict) else {}
        return LanguageModelReply(
            text=text, model=str(data.get("model") or self.model), usage={**reported, "provider_attempts": attempt}
        )

    def _post(self, body: dict[str, object]) -> httpx.Response:
        """One HTTP call. Raises _Transient for failures worth retrying and ProviderError for the rest."""
        try:
            response = httpx.post(self.url, json=body, headers=self.headers, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise _Transient(f"The provider did not answer within {self.timeout:g} seconds.") from exc
        except httpx.HTTPError as exc:
            raise _Transient(f"Could not reach the provider ({type(exc).__name__}).") from exc
        if response.status_code >= 500:
            # The body can echo the request, so only the status goes into the message.
            raise _Transient(f"The provider returned HTTP {response.status_code}.")
        if response.status_code != 200:
            raise ProviderError(f"The provider returned HTTP {response.status_code}.")
        return response
