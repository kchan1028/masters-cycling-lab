# 0002: Embedding model

Date: 2026-11-12. Status: accepted for the MVP; re-evaluate after the first dev-split results.

## Context

We need a small English embedding model that runs on a laptop CPU, has a clear licence and handles passages of
a few hundred tokens. Two candidates were checked against their model cards on Hugging Face:

| | BAAI/bge-small-en-v1.5 | sentence-transformers/all-MiniLM-L6-v2 |
|---|---|---|
| Licence | MIT | Apache-2.0 |
| Dimension | 384 | 384 |
| Max sequence length | 512 tokens | 256 tokens (trained on 128) |
| Built for | retrieval (short query → passage) | general sentence similarity |
| Layers | 12 | 6 |

## Decision

Use `BAAI/bge-small-en-v1.5` at revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`.

Facts from the pinned revision's files, which the code relies on:

- `modules.json`: Transformer → Pooling (CLS token) → Normalize. Embeddings come out unit-length, so cosine
  distance equals `1 - dot product`.
- `max_seq_length` 512, which includes the `[CLS]` and `[SEP]` tokens: 510 tokens of real text at most.
- Queries get the instruction prefix `Represent this sentence for searching relevant passages: `. Passages get
  no prefix. The prefix is part of the stored index configuration.

Chunking starts at 300 tokens with a 40-token overlap, counted with the model's own tokenizer. Every chunk is
checked against the 510-token limit before embedding; going over is an error, not a silent truncation. These
numbers are starting points to tune on the dev split only.

## Consequences

- The database column is `vector(384)`. A model with another dimension needs a migration and a full re-embed.
- Each index version stores model ID, revision, dimension, prefix and chunking settings. Vectors from different
  models or revisions are never compared with each other.
- The settings validator rejects revisions that are not full commit hashes, because branch names move.
- all-MiniLM-L6-v2 is faster but its 256-token limit forces smaller chunks. It is the first alternative to try if
  CPU ingestion is too slow.

## Review notes (added 2026-11-14)

Label: **Current Design**. Added during a documentation review; the decision above is unchanged.

**Alternatives.** `all-MiniLM-L6-v2` (table above). Smaller chunks at the same token budget were later tested on dev
and did not improve evidence coverage ([evaluation](../evaluation.md#experiments-dev-only)).

**Risks and limits.** A small English model trained for web-style retrieval; it is not tuned for sports-science
text, and passage-level evidence coverage (0.45 dev, 0.41 `test2`) is the main weakness. Changing the model means
re-embedding every document.

**When to revisit.** The record already says to re-evaluate after the first dev results. Those results are in, and
the cheap retrieval levers did not help ([0006](0006-retrieval-evaluation-method.md)), so a stronger or
domain-adapted embedding model is a candidate, judged on `dev` and confirmed on a fresh held-out split.
