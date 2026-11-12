# Dependencies and licences

Direct dependencies are pinned exactly in `backend/pyproject.toml` and `frontend/package.json`. The lockfiles
(`backend/uv.lock`, `frontend/package-lock.json`) pin everything else. `make bootstrap` installs from the lockfiles
and fails if they are out of date.

Versions were chosen on 2026-11-12: the newest release that is compatible with the rest of the stack, not
automatically the newest release.

## Tested toolchain

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12.7 | `backend/.python-version`. 3.12 has the widest wheel support for torch and PyMuPDF |
| uv | 0.13.7 | Resolves and installs the backend |
| Node.js | 24.21.0 (LTS) | `.nvmrc`. Vitest 5 and jsdom 31 need Node 22.12+; Node 20 is end-of-life |
| npm | bundled with Node 24 | |
| Docker / Compose | 27.4.0 / 2.31.0 | Used from milestone 1 |
| macOS arm64 | Darwin 25.6 | The only platform checked so far. Linux is exercised in Docker from milestone 1 |

## Backend

| Package | Version | Licence | Why |
|---|---|---|---|
| fastapi | 0.162.5 | MIT | HTTP API, OpenAPI |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server |
| pydantic / pydantic-settings | 2.14.3 / 2.16.2 | MIT | Request models, validated settings |
| sqlalchemy | 2.1.8 | MIT | ORM and query building (sync sessions) |
| alembic | 1.20.1 | MIT | Migrations |
| psycopg[binary] | 3.3.9 | LGPL-3.0-only | PostgreSQL driver. Bundles libpq |
| pgvector | 0.5.1 | MIT | `Vector` column type and distance operators for SQLAlchemy |
| pymupdf | 1.28.2 | AGPL-3.0 or Artifex commercial | PDF text, page labels, encryption checks |
| sentence-transformers | 6.3.0 | Apache-2.0 | Local embeddings |
| torch | 2.15.0 (CPU build on Linux) | BSD-style (several) | Required by sentence-transformers |
| httpx | 0.28.1 | BSD-3-Clause | LLM provider client, test client |
| pytest / ruff / mypy | 9.2.0 / 0.17.4 / 2.4.1 | MIT | Dev only |

Transitive packages include transformers 5.22.2, tokenizers, huggingface_hub, safetensors (Apache-2.0), numpy,
scipy, scikit-learn (BSD) and certifi, pathspec, tqdm (MPL-2.0, file-level copyleft, used unmodified).

### Deliberately not on the newest version

- **PyMuPDF 2.x.** 2.0 and 2.1 exist, but there is no reviewed changelog for the major version yet. 1.28.2 is the
  newest 1.x and matches the documentation used for the extractor. Revisit before milestone 2 ends.
- **SQLAlchemy 2.1** *is* used. Relevant changes from 2.0: autoflush now happens before `text()` statements too,
  and the generated `__init__` no longer sets omitted attributes.

## Frontend

| Package | Version | Licence | Ships to the browser |
|---|---|---|---|
| react / react-dom | 19.3.1 | MIT | yes (with `scheduler`, MIT) |
| vite / @vitejs/plugin-react | 8.3.8 / 6.3.0 | MIT | no |
| typescript | 5.9.3 | Apache-2.0 | no |
| vitest / jsdom | 5.1.0 / 31.0.0 | MIT | no |
| @testing-library/react, dom, jest-dom, user-event | 16.3.3, 10.4.1, 7.0.1, 14.6.10 | MIT | no |
| eslint / typescript-eslint | 10.14.0 / 8.72.2 | MIT | no |
| openapi-typescript | 7.13.0 | MIT | no |

Only React, React DOM and scheduler end up in the production bundle. The dev tooling is MIT, Apache-2.0, ISC,
BSD, MPL-2.0 or CC-BY-4.0 (browser data), all permissive or file-level copyleft.

### Deliberately not on the newest version

- **TypeScript 5.9, not 6.0 or 7.0.** `openapi-typescript` 7.13 requires TypeScript 5.x, and typescript-eslint
  8.72 supports up to 6.0. TypeScript 7 is the native compiler and is not supported by either yet.

### Known advisory

`npm audit` reports GHSA-g3hv-75wg-m249 (moderate, `minimatch` < 11.0.1, crafted glob patterns can be slow). It
comes in through ESLint 10 and typescript-eslint, which only see glob patterns from our own config. Dev-only, not
in the bundle. Forcing `minimatch` 11 would be a major-version override that ESLint does not declare support for,
so it is left as is and rechecked when ESLint updates.

## Embedding model

`BAAI/bge-small-en-v1.5`, MIT licence, pinned to revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`. Weights are
downloaded by `make download-model` (milestone 2) into a local cache and never committed. See
[decisions/0002](decisions/0002-embedding-model.md).

## Licensing implications

- **PyMuPDF is AGPL-3.0** unless you buy Artifex's commercial licence. Running this app privately on your own
  machine is fine. If you distribute it, or let other people use it over a network, the AGPL requires offering
  them the complete source of the application, including your changes. A closed-source or hosted product needs
  either the commercial licence or a different PDF library (pypdfium2 is Apache-2.0/BSD; pdfminer.six is MIT).
  The extractor sits behind one adapter so it can be swapped.
- **psycopg is LGPL-3.0.** Using it as an unmodified library is fine for distribution; modifying psycopg itself
  would mean sharing those changes.
- **MPL-2.0 packages** (certifi, pathspec, tqdm and some frontend tooling) only require sharing changes to those
  files.
- **The project itself has no licence yet.** Pick one before publishing the repository. Given PyMuPDF, AGPL-3.0
  is the simplest compatible choice for an open-source release.
- **Research PDFs** keep their own copyright. They are git-ignored; the corpus manifest records where each came
  from and whether it may be redistributed.
