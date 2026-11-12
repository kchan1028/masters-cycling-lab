import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from masters_cycling_lab.api.dependencies import SessionDep
from masters_cycling_lab.application import documents

router = APIRouter(prefix="/ingestion-jobs", tags=["ingestion"])


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    status: Literal["queued", "running", "succeeded", "failed", "canceled"]
    stage: Literal["extracting", "chunking", "embedding", "activating"] | None
    progress_done: int
    progress_total: int | None
    attempt_count: int
    max_attempts: int
    # A stable code (for example OCR_REQUIRED or PDF_ENCRYPTED) and a message that is safe to show.
    error_code: str | None
    error_message: str | None
    index_version_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@router.get("/{job_id}")
def get_job(session: SessionDep, job_id: uuid.UUID) -> JobOut:
    return JobOut.model_validate(documents.get_job(session, job_id))
