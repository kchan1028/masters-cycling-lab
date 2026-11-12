# 0004: Exact retrieval and server-resolved citations

Date: 2026-11-12. Status: accepted.

## Context

The first corpus is about 20 papers, a few thousand chunks. The point of the project is to see and measure what
retrieval does, and to make every citation traceable to a PDF page.

## Decision

**Exact search first.** Cosine distance with pgvector's `<=>` operator, ordered ascending, ties broken by chunk
ID. No HNSW index: at this size a sequential scan is fast and the results are exact. HNSW can be added later
only after comparing its recall against exact search, using `vector_cosine_ops`, and testing it with filters.

**Scores are not probabilities.** Responses show the cosine distance and `similarity = 1 - distance`. There is no
built-in relevance cut-off. If an abstention threshold is added, it is calibrated on the dev split and its
limits are written down.

**Lexical baseline.** PostgreSQL full-text search behind the same interface, so every evaluation compares vector
retrieval with a simple baseline. Results are kept even when the vector approach loses.

**Citations come from the server.** Passages sent to the LLM get request-local IDs (`E1`...). The exact text and
source metadata sent are stored in `query_evidence`. The model's structured answer may only reference those IDs.
Unknown IDs fail validation; there is one repair attempt, then a clear generation error. Page numbers, excerpts,
titles and file links in the response are read from storage, never taken from model output.

**Abstain without calling the model** when retrieval finds no usable evidence. A provider failure is a `503`
service error, never an "insufficient evidence" answer.

## Consequences

- Retrieval cost grows linearly with the corpus. Fine for hundreds of papers; revisit beyond that.
- Valid citation IDs only prove the citation is structurally correct. Whether the passage supports the claim is
  measured separately, by human review and labelled clearly when any automated judge is used.
