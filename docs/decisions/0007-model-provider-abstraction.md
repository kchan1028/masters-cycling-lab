# 0007: One OpenAI-compatible provider interface, optional for everything except answers

Date: 2026-11-14. Status: accepted. Label: **Current Design**.

## Context

Answers need a language model; uploading, indexing, search, the PDF viewer and retrieval evaluation do not. The
project has used a private OmniRoute gateway in front of `gemini-3.6-flash` on a free tier, which allows about a
dozen answers a day. Providers change quickly, and free tiers run out.

## Requirements and constraints

- Switching providers must not need code changes.
- Search and evaluation must keep working with no provider configured.
- A provider failure must never look like "not enough evidence": that would hide outages in answer statistics.
- Keys stay on the server, and only the question and the selected passages leave the machine.
- Answers must be reproducible enough to evaluate, so the exact model and prompt version are recorded.

## Alternatives considered

| Option | Why not |
|---|---|
| A vendor SDK (for example OpenAI or Google) | Ties the code to one provider and adds a dependency for one HTTP call |
| A multi-provider library (for example LiteLLM) | Useful for many providers, but a large dependency for one endpoint shape that most providers and gateways already offer |
| A RAG framework's model wrapper | Rejected with the frameworks in [0001](0001-stack-and-structure.md) |
| A small `LanguageModel` protocol and one OpenAI-compatible HTTP client (chosen) | One request shape, covered by gateways, local servers and hosted APIs |

## Decision

- `domain/ports.py` defines `LanguageModel` with one method, `complete(messages, max_tokens)`, and a
  `ProviderError`. Tests replace it with a fake.
- `infrastructure/llm/openai_compatible.py` posts to `{LLM_BASE_URL}/chat/completions` with `httpx`, with a
  configurable timeout (`LLM_TIMEOUT_SECONDS`, default 60). Timeouts, connection errors, non-2xx replies and
  malformed replies all become `ProviderError`.
- Generation is off until `LLM_BASE_URL` and `LLM_MODEL` are set. Without them, `POST /answers` returns
  `503 LLM_NOT_CONFIGURED`; everything else works.
- A provider failure returns `503 PROVIDER_UNAVAILABLE`. A reply that fails citation validation gets one repair
  request; a second failure returns `502 GENERATION_INVALID`.
- Each query run stores the model name, `PROMPT_VERSION` and the token usage exactly as the provider reported it.
- Operations guidance: pin one model rather than a gateway "combo" that falls back across models
  ([operations](../operations.md#answer-generation-llm-provider)).

## Rationale

The OpenAI chat-completions shape is the common denominator across hosted APIs, gateways and local servers, so one
client covers them. Keeping the protocol to a single method keeps the fake trivial and keeps provider details out
of the answering logic. Treating failures as service errors keeps outages out of abstention counts, which matters
because abstention accuracy is one of the things still to be measured.

## Consequences

- Swapping providers is a `.env` change, tested once with `make test-live`.
- Provider-specific features (tool calls, structured-output modes, prompt caching) are not used.
- There is no automatic retry or fallback provider. A transient failure surfaces as a `503` and the user asks again.
  `answer_run.py` resumes batch runs instead.

## Risks and limits

- "OpenAI-compatible" varies by provider: field names, usage reporting and error bodies differ. Only the gateway and
  model above have been checked live.
- Answers depend on a third party's model, which can change behind the same name. The stored model name records
  what the provider reported, not a guarantee that the weights are unchanged.
- Free tiers cap volume; the answer evaluation is blocked on that today ([handoff](../handoff.md#open-blockers)).
- Question text and passages leave the machine whenever an answer is requested ([SECURITY](../../SECURITY.md)).

## When to revisit

- If a second provider shape is needed that the chat-completions endpoint can't express.
- If transient failures become common enough to matter: add bounded retries with backoff for timeouts and 5xx
  replies only, and record attempts in `usage`.
- If answers are offered to anyone other than the operator: add per-request cost limits and provider fallbacks.
