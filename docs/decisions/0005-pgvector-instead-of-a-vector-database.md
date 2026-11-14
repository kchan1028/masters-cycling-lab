# 0005: PostgreSQL with pgvector instead of a dedicated vector database

Date: 2026-11-14. Status: accepted. Label: **Documented Rationale**.

The stack, including PostgreSQL with pgvector, was fixed by the project spec before any code was written
([0001](0001-stack-and-structure.md)). No dedicated vector database was trialled. This record writes down why the
choice still fits, using what the code now depends on, so the decision can be revisited on evidence.

## Context

Every search has to combine vector distance with relational facts: only live documents, only each document's
active and `ready` index version, only vectors from the query's embedding model and revision, and optional filters.
Ingestion publishes a new index version in one transaction ([0003](0003-postgres-job-queue-and-index-versions.md)).
The corpus is 20 papers and 1,269 passages.

## Requirements and constraints

- A reindex must never expose partial embeddings, and a stale worker must never publish.
- Vectors from different models or revisions must never be compared.
- Every citation must resolve to a stored passage, page and document (enforced with foreign keys).
- One person runs it on one machine with Docker Compose. Fewer services means less to operate and back up.
- A lexical baseline must sit behind the same interface for every evaluation ([0004](0004-retrieval-and-citations.md)).

## Alternatives considered

| Option | Why not, for now |
|---|---|
| A dedicated vector database next to PostgreSQL (for example Qdrant, Weaviate, Milvus) | Two stores to keep consistent. Activating an index version would become a cross-system write with no shared transaction, and the "never see partial work" rule would need an outbox or a two-phase pattern. One more service to run, secure and back up |
| A hosted vector service | Sends document text and vectors off the machine, needs credentials, costs money, and conflicts with the local, single-user design |
| An in-process index (FAISS or similar) saved to disk | No transactions, no foreign keys, and a second copy of the data to rebuild after every ingest or restore |
| PostgreSQL with pgvector (chosen) | Vectors, chunks, pages, index versions, answers and evaluation runs live in one database with one transaction model |

## Decision

Store embeddings in `chunk_embeddings` as `vector(384)` in the same PostgreSQL database as everything else. Search
with exact cosine distance (`<=>`) in SQL, joined to the active index version and filtered by embedding model and
revision (`application/retrieval.py`). Full-text search for the lexical baseline uses the same database.

## Rationale

- **Atomic publication.** Activation, retirement of the old version and the document's active pointer change in
  one transaction, fenced by the job's claim token. A second store would break that guarantee.
- **Integrity in the schema.** Composite foreign keys keep chunks, spans, evidence and citations inside the right
  index version and query run, so a bug fails instead of storing a broken citation.
- **One backup.** `make backup` takes one `pg_dump` that includes embeddings, answers and evaluation runs, plus the
  PDFs. Restore was verified end to end on 2026-11-12 ([operations](../operations.md#backup-and-restore)).
- **Scale fits.** Search p95 is 22 to 34 ms on CPU with a sequential scan at this size ([evaluation](../evaluation.md)).

## Consequences

- One service to run and one transaction model to reason about.
- Vector search competes with every other query for the same database's CPU and memory.
- Changing the embedding dimension needs a migration and a full re-embed (see [0002](0002-embedding-model.md)).

## Risks and limits

- Exact search grows linearly with the corpus. Nobody has measured where it stops being fast enough on this
  hardware.
- pgvector's approximate indexes (HNSW, IVFFlat) behave differently with filters than exact search. Adding one
  without measuring recall against exact results could quietly lower retrieval quality.
- The pinned image is pgvector 0.8.7 on PostgreSQL 17; upgrades follow PostgreSQL's own upgrade path.

## When to revisit

- Search p95 approaches the 500 ms engineering gate, or the corpus grows by an order of magnitude.
- An approximate index is needed: measure its recall against exact search on the dev split first (as 0004 says).
- A hosted, multi-user version is planned. Then a managed PostgreSQL with pgvector is the first option to price,
  because it keeps the transaction model ([architecture](../architecture.md#why-there-is-no-terraform-or-cloud-deployment)).
