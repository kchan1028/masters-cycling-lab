# API reference

The API is the FastAPI app in `backend/src/masters_cycling_lab/api/`. This page is a map; the OpenAPI spec is the
contract.

- **Interactive docs:** http://127.0.0.1:8000/api/docs when the API runs on the host (see the
  [README](../README.md#run-it)). The spec itself is served at `/api/openapi.json`.
- **Committed spec:** [`backend/openapi.json`](../backend/openapi.json). `make api-types` regenerates it and the
  frontend's TypeScript types. `make check-api-types`, which CI runs on every pull request, fails if either is out
  of date, so the file matches the code.

## Endpoints

All paths are under `/api/v1`.

| Area | Method and path | What it does |
|---|---|---|
| Health | `GET /health/live` | The process is running. Says nothing about the database or model |
| | `GET /health/ready` | Checks the database, migrations, the vector extension, file storage and model files. Returns 503 if any fail; never calls the LLM |
| Documents | `POST /documents` | Upload a PDF and queue it for ingestion (202). Uploading the same file again returns the existing document (200) |
| | `GET /documents` | List documents |
| | `GET /documents/{document_id}` | One document and its status |
| | `PATCH /documents/{document_id}` | Correct bibliographic metadata; send only the fields to change |
| | `DELETE /documents/{document_id}` | Remove the document, file, indexes and any answers that quoted it. Cannot be undone |
| | `GET /documents/{document_id}/file` | The PDF |
| | `GET /documents/{document_id}/pages/{page_number}` | Stored text of one physical page, with extraction warnings |
| Ingestion | `POST /documents/{document_id}/ingestions` | Rebuild the index (202). The current index stays searchable until the new one is ready |
| | `GET /ingestion-jobs/{job_id}` | Job status |
| Search | `POST /retrieval/search` | Rank passages from active, fully indexed documents with exact search |
| Answers | `POST /answers` | Answer with citations. Abstains without calling the model when nothing relevant is found. 503 when generation is off or the provider fails; 502 when the model keeps returning invalid output |
| | `GET /answers/{query_run_id}` | A stored answer |
| | `GET /answers/{query_run_id}/debug` | Every retrieved candidate, whether it was sent and why, budgets, models and timings. No raw prompt |
| Evaluation | `GET /evaluation-runs` | Stored retrieval evaluation runs |
| | `GET /evaluation-runs/{run_id}` | One run with its settings and scores |

## Errors

Every non-2xx response has the same shape:

```json
{"error": {"code": "NOT_FOUND", "message": "…", "request_id": "…", "details": {}}}
```

`code` is meant for programs and `message` for people. Validation errors return `VALIDATION_ERROR` (422) with
each failing field's location and reason in `details.errors`, without echoing the submitted values, which can
contain a whole question or document. Unexpected failures return `INTERNAL_ERROR` (500).

## Access and limits

There is no authentication: the API is for one person on one machine. Requests must carry a `Host` in
`ALLOWED_HOSTS`, and browser writes must come from the app's origin or `ALLOWED_ORIGINS`. Uploads are capped by
`MAX_UPLOAD_BYTES`. [Architecture](architecture.md#security-boundaries) explains why.
