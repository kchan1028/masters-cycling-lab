"""The ingestion worker: claim a job, build its index version, repeat. Run one per machine (CPU embeddings)."""

import logging
import os
import signal
import socket
import threading

from sqlalchemy.exc import OperationalError

from masters_cycling_lab.application.ingestion import JobRunner, claim_next_job
from masters_cycling_lab.config import Settings, get_settings
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import (
    ModelNotDownloaded,
    SentenceTransformerEmbedder,
)
from masters_cycling_lab.infrastructure.pdf.pymupdf_extractor import extract_pdf
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage

log = logging.getLogger("masters_cycling_lab.worker")
RETRY_SECONDS = 30


def load_embedder(settings: Settings, stop: threading.Event) -> SentenceTransformerEmbedder | None:
    # Wait instead of crashing, so `make up` works before `make download-model` and picks the model up after.
    while not stop.is_set():
        try:
            return SentenceTransformerEmbedder(settings)
        except ModelNotDownloaded as exc:
            log.error("%s Checking again in %s seconds.", exc, RETRY_SECONDS)
            stop.wait(RETRY_SECONDS)
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    stop = threading.Event()
    # Finish the current job step, then exit. A job cut off mid-way is picked up again when its lease expires.
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    engine = make_engine(settings.database_url)
    storage = LocalFileStorage(settings.storage_root)
    if removed := storage.remove_stale_temp_files():
        log.info("Removed %s partial uploads left by an earlier crash", removed)

    embedder = load_embedder(settings, stop)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    if embedder is not None:
        log.info("Worker %s ready with %s@%s", worker_id, embedder.model_id, embedder.revision[:7])

    while embedder is not None and not stop.is_set():
        try:
            claim = claim_next_job(engine, worker_id)
        except OperationalError:
            log.error("Database unavailable; retrying in %s seconds", RETRY_SECONDS)
            stop.wait(RETRY_SECONDS)
            continue
        if claim is None:
            stop.wait(settings.worker_poll_seconds)
            continue
        log.info("Job %s: claimed (attempt %s)", claim.job_id, claim.attempt)
        try:
            JobRunner(engine, storage, embedder, extract_pdf, settings, claim).run()
        except Exception:
            # Usually the database went away mid-job. Keep the worker alive; the job's lease expires and a later
            # claim picks it up again.
            log.exception(
                "Job %s: could not record the outcome; it will be retried after its lease expires", claim.job_id
            )

    engine.dispose()
    log.info("Worker stopped")
