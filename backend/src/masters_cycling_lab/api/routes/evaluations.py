"""Read-only access to evaluation runs. Runs are started from the command line (`make evaluate`), not the API."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from masters_cycling_lab.api.dependencies import SessionDep
from masters_cycling_lab.application.errors import NotFound
from masters_cycling_lab.infrastructure.db.models import EvaluationResult, EvaluationRun

router = APIRouter(prefix="/evaluation-runs", tags=["evaluations"])


class EvaluationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    split: str
    status: str
    dataset_sha256: str
    corpus_sha256: str
    code_revision: str | None
    config: dict[str, Any]
    # Automated retrieval metrics per mode. Human judgments of answers are recorded separately (milestone 6).
    metrics: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None


class EvaluationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    question_id: str
    retrieval: dict[str, Any]
    metrics: dict[str, Any]


class EvaluationRunDetail(EvaluationRunOut):
    results: list[EvaluationResultOut]


class EvaluationRunList(BaseModel):
    items: list[EvaluationRunOut]
    total: int
    limit: int
    offset: int


@router.get("")
def list_runs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvaluationRunList:
    total = session.scalar(select(func.count()).select_from(EvaluationRun)) or 0
    runs = session.scalars(
        select(EvaluationRun).order_by(EvaluationRun.started_at.desc(), EvaluationRun.id).limit(limit).offset(offset)
    )
    return EvaluationRunList(
        items=[EvaluationRunOut.model_validate(run) for run in runs], total=total, limit=limit, offset=offset
    )


@router.get("/{run_id}")
def get_run(session: SessionDep, run_id: uuid.UUID) -> EvaluationRunDetail:
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise NotFound("EVALUATION_RUN_NOT_FOUND", "No evaluation run with this ID.")
    results = session.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.evaluation_run_id == run_id)
        .order_by(EvaluationResult.question_id)
    )
    return EvaluationRunDetail(
        **EvaluationRunOut.model_validate(run).model_dump(),
        results=[EvaluationResultOut.model_validate(result) for result in results],
    )
