import argparse
import json
import time
import uuid
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from masters_cycling_lab.application import documents
from masters_cycling_lab.application.errors import ServiceError
from masters_cycling_lab.config import get_settings
from masters_cycling_lab.infrastructure.db.models import IndexVersion, IngestionJob
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage
from masters_cycling_lab.main import create_app

FINISHED = ("succeeded", "failed", "canceled")


def write_openapi(path: Path) -> int:
    schema = create_app().openapi()
    path.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Wrote {path}")
    return 0


def download_model() -> int:
    # Imported here because loading torch takes seconds, and the other commands don't need it.
    from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import (
        SentenceTransformerEmbedder,
    )

    settings = get_settings()
    embedder = SentenceTransformerEmbedder(settings, allow_download=True)
    print(
        f"{embedder.model_id}@{embedder.revision} is in {settings.model_cache_dir}: "
        f"{embedder.dimension} dimensions, up to {embedder.max_tokens} tokens."
    )
    return 0


def ingest(path: Path, filename: str | None, wait: bool) -> int:
    """Upload one PDF the same way the API does. The worker does the actual ingestion."""
    settings = get_settings()
    engine = make_engine(settings.database_url)
    storage = LocalFileStorage(settings.storage_root)
    try:
        with Session(engine) as session, path.open("rb") as file:
            view, duplicate = documents.upload_document(session, storage, settings, filename or path.name, file, {})
            # Read what we need while the session is open; the objects expire when it closes.
            document_id = view.document.id
            job_id, job_status = (view.latest_job.id, view.latest_job.status) if view.latest_job else (None, None)
    except ServiceError as error:
        print(f"Not uploaded ({error.code}): {error.message}")
        return 1

    print(f"{'Already in the corpus' if duplicate else 'Queued'}: document {document_id}")
    if job_id is None:
        return 0
    if not wait:
        print(f"Ingestion job {job_id} is {job_status}.")
        return 0
    return wait_for_job(engine, job_id)


def wait_for_job(engine: Engine, job_id: uuid.UUID) -> int:
    last_line = ""
    while True:
        with Session(engine) as session:
            job = session.get_one(IngestionJob, job_id)
            line = f"{job.status} {job.stage or ''} {job.progress_done}/{job.progress_total or '?'}".strip()
            if line != last_line:
                print(line)
                last_line = line
            if job.status == "succeeded" and job.index_version_id:
                version = session.get_one(IndexVersion, job.index_version_id)
                print(f"Ready: {version.page_count} pages, {version.chunk_count} chunks.")
                return 0
            if job.status in FINISHED:
                print(f"{job.status}: {job.error_code or ''} {job.error_message or ''}".strip())
                return 1
        time.sleep(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcl", description="Masters Cycling Lab command line tools")
    commands = parser.add_subparsers(dest="command", required=True)

    openapi = commands.add_parser("openapi", help="write the API's OpenAPI schema as JSON")
    openapi.add_argument("output", type=Path)

    commands.add_parser("download-model", help="download the pinned embedding model into MODEL_CACHE_DIR")

    ingest_command = commands.add_parser("ingest", help="upload one PDF and queue it for the worker")
    ingest_command.add_argument("path", type=Path)
    ingest_command.add_argument("--filename", help="name to record for the document (default: the file's name)")
    ingest_command.add_argument("--wait", action="store_true", help="wait for the worker and show progress")

    args = parser.parse_args(argv)
    if args.command == "openapi":
        return write_openapi(args.output)
    if args.command == "download-model":
        return download_model()
    return ingest(args.path, args.filename, args.wait)
