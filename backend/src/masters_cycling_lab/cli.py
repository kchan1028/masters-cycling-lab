import argparse
import json
import subprocess
import time
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from masters_cycling_lab.application import corpus, documents, evaluation
from masters_cycling_lab.application.errors import ServiceError
from masters_cycling_lab.config import REPO_ROOT, get_settings
from masters_cycling_lab.infrastructure.db.models import Document, IndexVersion, IngestionJob
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage
from masters_cycling_lab.main import create_app
from masters_cycling_lab.smoke import run_smoke

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


def corpus_command(action: str, manifest: Path, check_index: bool, wait: bool) -> int:
    try:
        entries = corpus.load_manifest(manifest)
    except corpus.ManifestError as error:
        print(f"Problems in {manifest}:\n{error}")
        return 1

    if action == "download":
        outcomes = corpus.download_missing(manifest, entries)
        for corpus_id, outcome in outcomes:
            print(f"{corpus_id}: {outcome}")
        return 0 if all(outcome in ("already present", "downloaded") for _, outcome in outcomes) else 1

    if action == "verify":
        checks = corpus.verify_files(manifest, entries)
        for check in checks:
            print(f"{check.corpus_id}: {'ok' if not check.problems else '; '.join(check.problems)}")
        print(f"\n{len(entries)} papers, {sum(e.full_text for e in entries)} with full text.")
        for relevance, count in sorted(Counter(e.population_relevance for e in entries).items()):
            print(f"  {relevance}: {count}")
        provisional = sum(e.description_review_status == "provisional" for e in entries)
        print(f"Population descriptions awaiting human review: {provisional}")
        if check_index:
            print_index_status(entries)
        failed = [check for check in checks if check.problems]
        print(f"\n{'All files match the manifest.' if not failed else f'{len(failed)} files have problems.'}")
        return 1 if failed else 0

    settings = get_settings()
    engine = make_engine(settings.database_url)
    with Session(engine) as session:
        results = corpus.ingest(session, LocalFileStorage(settings.storage_root), settings, manifest, entries)
        for entry, _, duplicate in results:
            print(f"{entry.corpus_id}: {'already in the corpus, metadata refreshed' if duplicate else 'queued'}")
    if not wait:
        return 0
    return wait_for_corpus(engine, entries)


def print_index_status(entries: list[corpus.ManifestEntry]) -> None:
    try:
        with Session(make_engine(get_settings().database_url)) as session:
            status = corpus.index_status(session, entries)
    except OperationalError as exc:
        print(
            f"\nIndex status unavailable: could not use the database ({type(exc.orig).__name__}). Is `make up` running?"
        )
        return
    print("\nIndex status:")
    for state, count in sorted(Counter(status.values()).items()):
        print(f"  {state}: {count}")


def wait_for_corpus(engine: Engine, entries: list[corpus.ManifestEntry]) -> int:
    last = ""
    while True:
        with Session(engine) as session:
            status = corpus.index_status(session, entries)
            ids = list(
                session.scalars(
                    select(Document.id).where(
                        Document.sha256.in_([entry.sha256 for entry in entries]), Document.deleted_at.is_(None)
                    )
                )
            )
            jobs = documents.latest_jobs(session, ids)
            running = sum(job.status in ("queued", "running") for job in jobs.values())
            failed = [job for job in jobs.values() if job.status == "failed"]
            line = f"searchable {list(status.values()).count('searchable')}/{len(entries)}, in progress {running}"
            if line != last:
                print(line)
                last = line
            if running == 0:
                for job in failed:
                    print(f"failed: document {job.document_id}: {job.error_code} {job.error_message}")
                return 0 if all(state == "searchable" for state in status.values()) else 1
        time.sleep(3)


def evaluate(split: str, modes: list[str], k: int, check_only: bool) -> int:
    settings = get_settings()
    try:
        questions = evaluation.load_questions(evaluation.DEFAULT_QUESTIONS)
        entries = corpus.load_manifest(corpus.DEFAULT_MANIFEST)
    except (evaluation.LabelError, corpus.ManifestError) as error:
        print(f"Label or manifest problems:\n{error}")
        return 1
    engine = make_engine(settings.database_url)
    with Session(engine) as session:
        index = evaluation.corpus_index(session, entries)
        _, problems = evaluation.locate_evidence(session, questions, index)
        print(f"{len(questions)} questions; every gold quotation checked against the stored page text.")
        if problems:
            print("\n".join(problems))
            return 1
        print("All gold quotations were found on their stated pages.")
        if check_only:
            return 0
        if split == "test":
            print("Note: the test split is held out. Use it to report results, not to tune settings.")

        from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import (
            SentenceTransformerEmbedder,
        )

        run_id, artifact, summary = evaluation.run_evaluation(
            session,
            SentenceTransformerEmbedder(settings),
            questions,
            entries,
            split=split,
            modes=tuple(modes),  # type: ignore[arg-type]
            k=k,
            dataset_sha256=evaluation.file_sha256(evaluation.DEFAULT_QUESTIONS),
            corpus_sha256=evaluation.file_sha256(corpus.DEFAULT_MANIFEST),
            code_revision=code_revision(),
            artifacts_dir=REPO_ROOT / "artifacts" / "evaluations",
        )
    print(f"\nEvaluation run {run_id} ({split}); artifact: {artifact}")
    for mode, scores in summary.items():
        print(f"\n{mode}:")
        for name, value in scores.items():
            if not name.endswith("_questions"):
                print(f"  {name}: {value}")
    return 0


def code_revision() -> str | None:
    """The git commit, with "-dirty" when there are uncommitted changes. None outside a git checkout."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=REPO_ROOT)
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=REPO_ROOT)
    except (OSError, subprocess.CalledProcessError):
        return None
    return commit.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


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

    corpus_command_parser = commands.add_parser("corpus", help="research corpus: download, verify or ingest")
    corpus_command_parser.add_argument("action", choices=["download", "verify", "ingest"])
    corpus_command_parser.add_argument("--manifest", type=Path, default=corpus.DEFAULT_MANIFEST)
    corpus_command_parser.add_argument("--check-index", action="store_true", help="also report ingestion status")
    corpus_command_parser.add_argument("--wait", action="store_true", help="after ingest, wait for the worker")

    evaluate_parser = commands.add_parser("evaluate", help="run the labelled retrieval evaluation")
    evaluate_parser.add_argument("--split", choices=["dev", "test"], default="dev")
    evaluate_parser.add_argument("--modes", nargs="+", choices=["vector", "lexical"], default=["vector", "lexical"])
    evaluate_parser.add_argument("--k", type=int, default=10, help="passages retrieved per question")
    evaluate_parser.add_argument("--check-labels", action="store_true", help="only check the gold quotations")

    smoke_parser = commands.add_parser("smoke", help="end-to-end check against a running stack")
    smoke_parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="the frontend's address")

    args = parser.parse_args(argv)
    if args.command == "openapi":
        return write_openapi(args.output)
    if args.command == "download-model":
        return download_model()
    if args.command == "evaluate":
        return evaluate(args.split, args.modes, args.k, args.check_labels)
    if args.command == "corpus":
        return corpus_command(args.action, args.manifest, args.check_index, args.wait)
    if args.command == "smoke":
        return run_smoke(args.base_url)
    return ingest(args.path, args.filename, args.wait)
