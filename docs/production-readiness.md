# Production readiness

An honest assessment of where Masters Cycling Lab stands, area by area, as of 2026-11-14 (commit `4d2eaeb`).

**Summary.** This is a local, single-user research tool that works and has been checked end to end. It is **not
production-ready** for anyone other than its operator, and it is not meant to be: it has no authentication by design,
runs only under Docker Compose on `127.0.0.1`, and its answer quality is only partly evaluated. Passing tests and CI
show the code does what it was built to do. They don't show it is safe or reliable to run for other people.

The material risks, with impact, likelihood and next actions, are in the [risk register](risk-register.md).

## Status key

| Status | Meaning |
|---|---|
| **Verified** | Implemented and checked by a test, a recorded run or a documented manual check |
| **Implemented** | In the code, but not independently checked beyond normal use |
| **Partial** | Some of it exists; the gaps are named |
| **Planned** | Not built; listed in the roadmap, handoff or a decision record |
| **Not applicable** | Out of scope for a local single-user app, with the reason |

## Assessment

| Area | Status | Evidence | Gaps and limits |
|---|---|---|---|
| Unit, contract and frontend tests | Verified | `make test` (pytest and Vitest, offline) runs in CI on every PR and every push to `main` | |
| Integration and model tests | Partial | `make test-integration` runs in CI on every PR and push to `main` against a pgvector service container ([operations](operations.md#continuous-integration)); `make test-model` passes locally ([handoff](handoff.md#checks-run)) | `make test-model` is not in CI because it downloads the model, so a change to embedding code can merge without it |
| End-to-end check | Verified | `make smoke`: upload, index, search, page, file, answer, delete against the running stack | Run by hand. The answer step is skipped without a provider |
| CI | Verified | [code-quality.yml](../.github/workflows/code-quality.yml): lint, type checks, tests, OpenAPI drift check, build; read-only token, pinned actions, no secrets | Branch protection and required checks are GitHub settings, not visible in the repo |
| Dependencies | Verified | `uv.lock` and `package-lock.json`; dependency review blocks high and critical advisories on PRs; Dependabot for uv, npm, Dockerfiles, Compose and actions; [dependencies.md](dependencies.md) records versions and licences | Container images are pinned by tag, not digest. Major-version Dependabot PRs are open and unreviewed |
| Authentication and authorization | Not applicable | Single trusted user on their own machine ([SECURITY](../SECURITY.md)) | Becomes the first blocker for any shared or hosted use |
| Network exposure | Verified | Published ports bound to `127.0.0.1`; `frontend` cannot reach `db` (separate networks); `Host` allowlist against DNS rebinding; origin check on writes | Exposure depends on the operator not editing `compose.yaml` |
| Input validation | Verified | Upload type, size (`MAX_UPLOAD_BYTES`) and page limits (`MAX_PDF_PAGES`); generated storage keys; settings validated at startup; Pydantic request models; contract test against `openapi.json` | No OCR; malformed PDFs fail with stable error codes |
| Document security (untrusted PDFs) | Implemented | Parsing runs in the worker container, capped at 3 GB and 2 CPUs; the server never fetches URLs | PyMuPDF parses untrusted files in-process. No sandbox beyond the container |
| Prompt injection | Partial | Document text is treated as untrusted; the model can cite only passages it was sent; citations are rebuilt from storage; the browser escapes document text | Injected text can still steer the wording of an answer. No adversarial test set |
| Secrets | Implemented | `.env` is git-ignored; the LLM key is a `SecretStr` and never sent to the browser; CI uses no secrets | The example database password is public and must be changed by hand |
| Data protection | Partial | Logs leave out questions, document text and provider payloads; deletion removes the file, index and answers that quoted it | Questions and passages go to the configured LLM provider. Older evaluation runs keep up to 300 characters per passage. Backups are unencrypted |
| Error handling | Verified | Stable error codes in one envelope; provider failure is `503`, never "not enough evidence"; invalid model output gets one repair, then `502` | |
| Retries | Partial | Ingestion jobs retry with backoff, bounded by `attempt_count`; leases recover jobs from dead workers | LLM calls have a timeout but no retry. Transient provider errors surface as `503` |
| Observability | Partial | Liveness and readiness endpoints (readiness checks the database, migrations, vector extension, storage and model files); per-answer timings and token usage stored; plain-text logs | No metrics, tracing, dashboards or alerts. Nobody is paged; this is a local tool |
| Deployment | Implemented | Docker Compose with health-checked start order, one-shot migrations, non-root containers | Local only. No cloud deployment by design ([architecture](architecture.md#why-there-is-no-terraform-or-cloud-deployment)) |
| Rollback | Partial | Index versions switch atomically and the previous version is kept, so a bad reindex can be undone in data | No release tags or documented code rollback. Migration downgrades are tested on an empty database only; the `test2` downgrade fails while `test2` runs exist |
| Database operations | Partial | Alembic is the only schema change path; a migration test checks models and migrations agree | Retired index versions are never cleaned up. No vacuum, index or growth monitoring |
| Backup and restore | Verified | `make backup` / `make restore` with checksums; restore verified end to end on 2026-11-12 ([operations](operations.md#backup-and-restore)) | Manual, not scheduled. Backups stay on the same machine unless copied off |
| Retrieval quality | Partial | 74 human-reviewed questions, dev and held-out splits, committed artifacts ([evaluation](evaluation.md)) | Recall@10 0.76 to 0.77 (target 0.80) and evidence coverage 0.41 to 0.45 (target 0.60) miss their targets |
| Answer quality | Partial | Citation validity enforced on every answer; 19 of 19 claims supported in the first 7 rated answers | One rater, small and easy sample. Abstention on no-evidence and out-of-scope questions untested |
| Performance | Verified | Search p95 22 to 34 ms on CPU, under the 500 ms gate | Ingestion takes about 10 minutes for 20 papers on CPU. Answer generation took a median 25 s with the tested model. No load testing, which a single-user app doesn't need |
| Cost | Partial | Everything except answers runs locally at no per-use cost; token usage is stored per answer | No spending cap in the app. Cost control is the provider key's own limit |
| Licensing | Implemented | [dependencies.md](dependencies.md#licensing-implications) explains PyMuPDF's AGPL-3.0 | Matters before distributing the app or running it for others. The project has no licence yet |

## Known limitations

- Local and single-user, with no authentication. Don't expose it beyond `127.0.0.1`.
- Passage retrieval is the main weakness, and answer evaluation is partial (see above).
- No OCR; two-column pages can interleave; tables lose layout; figures are skipped.
- A small evaluation set: one question moves an average by about 3 points on dev and 6 on `test2`.

## What would change before shared or hosted use

In order, from the [architecture](architecture.md#why-there-is-no-terraform-or-cloud-deployment) and the risk
register:

1. Authentication and per-user authorization.
2. Object storage for PDFs and a managed PostgreSQL with pgvector, automated backups and restore drills.
3. Integration tests in CI with a PostgreSQL service container.
4. Bounded LLM retries, per-request cost limits and a provider decision with a data-processing agreement.
5. Metrics and alerts for ingestion failures, provider errors and search latency.
6. A finished answer evaluation, including abstention, with a second rater.
7. A licence decision that accounts for PyMuPDF's AGPL-3.0.
