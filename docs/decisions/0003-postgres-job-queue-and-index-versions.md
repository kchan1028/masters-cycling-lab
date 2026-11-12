# 0003: PostgreSQL job queue and index versions

Date: 2026-11-12. Status: accepted.

## Context

Ingestion is slow (extraction plus CPU embeddings) and can fail half way. Workers can be killed. A reindex must not
take a working document out of search, and a worker that stalled must not overwrite newer work when it wakes up.

## Decision

**Queue.** `ingestion_jobs` in PostgreSQL. A worker claims the oldest runnable job with
`SELECT ... FOR UPDATE SKIP LOCKED`, sets `status = running`, a new random `claim_token`, `worker_id` and
`lease_expires_at`, and commits before doing any work. While working it renews the lease with a heartbeat that
matches on `claim_token`. Jobs whose lease has expired are claimable again.

**Fencing.** Every write the worker makes for a job (pages, chunks, embeddings, status changes, activation)
happens in a statement that also checks the job's `claim_token` is still the one it was given. If the token
changed, the write affects zero rows and the worker stops. A stale worker can therefore never publish.

**Retries.** Bounded by `attempt_count`, with `available_after` backoff. Permanent problems (encrypted, corrupt,
image-only PDF) fail immediately with a stable error code. Transient problems (database, out of memory) retry.

**Index versions.** Each ingestion run writes into a new `index_versions` row in status `building`. When all
pages, chunks and embeddings are stored and validated, one transaction marks it `ready`, marks the previous
version `retired` and points `documents.active_index_version_id` at it. Retrieval joins on the active pointer and
`status = 'ready'`, so it never sees partial work.

**One active job per document**, enforced by a partial unique index on `ingestion_jobs(document_id)` where status
is `queued` or `running`.

## Consequences

- No extra infrastructure, and the queue is inspectable with SQL.
- Polling adds up to `WORKER_POLL_SECONDS` of latency. `LISTEN/NOTIFY` can be added later if that matters.
- Retired index versions keep their rows until cleaned up, which costs disk but makes rollback easy.
