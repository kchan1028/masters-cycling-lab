"""A small harness for driving uploads and the worker step by step in integration tests."""

import io
import uuid
from dataclasses import dataclass

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from masters_cycling_lab.application import documents
from masters_cycling_lab.application.ingestion import Claim, JobRunner, claim_next_job
from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.ports import Embedder, PdfExtractor
from masters_cycling_lab.infrastructure.db.models import Document, IndexVersion, IngestionJob
from masters_cycling_lab.infrastructure.pdf.pymupdf_extractor import extract_pdf
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage
from tests.helpers import FakeEmbedder, make_pdf

WORDS = "masters cyclists older endurance athletes recovery strength training intensity heart power cadence"


def paper_pages(page_count: int = 4) -> list[str]:
    """Pages with a running header and a page number, like a journal article."""
    pages = []
    for number in range(1, page_count + 1):
        sentences = [f"Sentence {number}.{i} on {WORDS.split()[i % 12]} in {WORDS}." for i in range(6)]
        pages.append(f"Journal of Masters Cycling 2024\n{' '.join(sentences)}\n{number}")
    return pages


def sample_pdf(password: str | None = None) -> bytes:
    return make_pdf(paper_pages(), title="Recovery in Masters Cyclists", roman_labels=True, password=password)


@dataclass
class Lab:
    settings: Settings
    engine: Engine
    storage: LocalFileStorage

    def upload(self, pdf: bytes, filename: str = "paper.pdf") -> uuid.UUID:
        with Session(self.engine) as session:
            view, _ = documents.upload_document(session, self.storage, self.settings, filename, io.BytesIO(pdf), {})
            return view.document.id

    def claim(self, worker_id: str = "worker-a") -> Claim:
        claim = claim_next_job(self.engine, worker_id)
        assert claim is not None, "expected a job to claim"
        return claim

    def runner(self, claim: Claim, embedder: Embedder | None = None, extract: PdfExtractor = extract_pdf) -> JobRunner:
        return JobRunner(
            self.engine, self.storage, embedder or FakeEmbedder(self.settings), extract, self.settings, claim
        )

    def ingest_next(self) -> None:
        self.runner(self.claim()).run()

    def expire_lease(self, job_id: uuid.UUID) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("update ingestion_jobs set lease_expires_at = now() - interval '1 second' where id = :id"),
                {"id": job_id},
            )

    def document(self, document_id: uuid.UUID) -> Document | None:
        with Session(self.engine, expire_on_commit=False) as session:
            return session.get(Document, document_id)

    def job(self, job_id: uuid.UUID) -> IngestionJob:
        with Session(self.engine, expire_on_commit=False) as session:
            return session.get_one(IngestionJob, job_id)

    def versions(self, document_id: uuid.UUID) -> list[IndexVersion]:
        with Session(self.engine, expire_on_commit=False) as session:
            query = (
                select(IndexVersion).where(IndexVersion.document_id == document_id).order_by(IndexVersion.created_at)
            )
            return list(session.scalars(query))
