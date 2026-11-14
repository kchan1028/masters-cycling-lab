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
happens in a transaction that first locks the job row (`SELECT ... FOR UPDATE`) and checks that the job is still
running with this worker's `claim_token` and an unexpired lease. If not, the transaction rolls back and the worker
stops. The row lock is held until commit, so a takeover cannot slip in between the check and the write. A stale
worker can therefore never publish. The same transaction renews the lease, so each write doubles as a heartbeat.

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

## Review notes (added 2026-11-14)

Label: **Current Design**. Added during a documentation review; the decision above is unchanged.

**Alternatives.** Celery or RQ with Redis (ruled out in [0001](0001-stack-and-structure.md)); in-place reindexing
that overwrites the current version.

**Risks and limits.** Retired index versions are kept until cleaned up and use disk; no cleanup job exists yet. A
worker killed repeatedly (seen once, most likely memory) ends jobs in `WORKER_LOST`, and Reindex recovers them
([handoff](../handoff.md#checks-run)). Polling adds up to `WORKER_POLL_SECONDS` of latency.

**When to revisit.** Multiple workers on separate machines, many more documents per hour, or a need for
priorities would justify `LISTEN/NOTIFY` or a broker. Disk use from retired versions would justify a cleanup job.
