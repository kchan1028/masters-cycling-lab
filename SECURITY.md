# Security policy

Masters Cycling Lab is a single-user app meant to run on your own machine. It has no login. Read
[What the app protects against](#what-the-app-protects-against) before you change how it is exposed.

## Supported versions

Only the latest commit on `main` gets fixes. There are no releases or backports.

## Reporting a vulnerability

Please report privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability**. Don't open a public issue or pull request for a security problem.

Include what you found, the commit you tested, steps to reproduce, and what an attacker could do with it. This is a
side project maintained by one person, so expect a reply within a couple of weeks. Fixes land on `main`, and the
report is credited unless you'd rather stay anonymous.

## What the app protects against

The threat model assumes one trusted person using the app on their own computer. Within that:

- **Network exposure.** Every published port is bound to `127.0.0.1` (`8080` for the app, `5433` for PostgreSQL).
  The API itself is reachable only inside Docker, through the frontend's nginx proxy.
- **Other web pages in your browser.** The API rejects any request whose `Host` is not in `ALLOWED_HOSTS`, which
  blocks DNS rebinding. Writes (`POST`, `PUT`, `PATCH`, `DELETE`) must come from the app's own origin or from
  `ALLOWED_ORIGINS`. CORS is only there for the Vite dev server and is not access control.
- **Hostile PDFs.** Uploads must look like a PDF and stay under `MAX_UPLOAD_BYTES` and `MAX_PDF_PAGES`. Files are
  stored under generated keys; a filename is metadata and never becomes a path. Parsing runs in the worker container,
  not the API, capped at 3 GB of memory and 2 CPUs. The server never fetches URLs it was given.
- **Prompt injection from documents.** Document text is treated as untrusted input to the language model. The server
  accepts only citations to passages it actually sent, and the browser escapes document text when it renders it.
- **Secrets.** Settings live in `.env`, which git ignores. The LLM API key is held as a secret value on the server and
  is never sent to the browser. Logs leave out full questions, document text and provider payloads, and validation
  errors leave out the submitted values.
- **Supply chain at run time.** The embedding model is pinned to a commit hash, and containers run with
  `HF_HUB_OFFLINE=1`; `make download-model` is the only step that downloads it. Python and npm dependencies are
  installed from lock files.

## Out of scope

These are known limits of the design, not vulnerabilities:

- **No authentication or authorization.** Anyone who can reach port `8080` can read, upload and delete everything.
  Exposing the app on a LAN, a public address or through a tunnel is unsupported. Shared or remote use needs
  authentication added first.
- **Data sent to your LLM provider.** When you ask for an answer, the question and the selected passages go to the
  provider in `LLM_BASE_URL`. Pick a provider you trust with that content, or leave `LLM_BASE_URL` empty to keep
  everything local.
- **Anyone with access to your machine or Docker.** They can read `.env`, the database volume and the stored PDFs.
- **Scanned or encrypted PDFs** are rejected (`OCR_REQUIRED`, `PDF_ENCRYPTED`), not processed.

## Keeping your install safe

- Set your own `POSTGRES_PASSWORD` in `.env` (and the same one in `DATABASE_URL`). The example value is public.
- Keep the `127.0.0.1:` prefix on every port in `compose.yaml`. If you don't use `psql` or the integration tests from
  the host, remove the `db` port entirely.
- Add names to `ALLOWED_HOSTS` and `ALLOWED_ORIGINS` only for your own machine or dev server.
- Give this app its own LLM API key with a spending limit, so you can revoke it without affecting anything else.
- Never commit `.env`, research PDFs or backups. `.gitignore` already excludes them; check `git status` before you
  push.
- `make backup` copies the whole database and every PDF into `backups/`. Store those copies as carefully as the
  originals.

## Licensing note

PyMuPDF is AGPL-3.0. That matters if you distribute the app or run it for other people. See
[docs/dependencies.md](docs/dependencies.md#licensing-implications).
