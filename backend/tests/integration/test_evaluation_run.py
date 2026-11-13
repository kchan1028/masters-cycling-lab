import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from masters_cycling_lab.application import evaluation
from masters_cycling_lab.application.corpus import ManifestEntry, load_manifest
from masters_cycling_lab.main import create_app
from tests.helpers import FakeEmbedder, manifest_entry, write_manifest
from tests.integration.lab import Lab, sample_pdf
from tests.unit.test_evaluation import question


def setup_corpus(lab: Lab, tmp_path: Path) -> list[ManifestEntry]:
    pdf = sample_pdf()
    lab.upload(pdf)
    lab.ingest_next()
    return load_manifest(write_manifest(tmp_path, manifest_entry(pdf, title="Recovery in Masters Cyclists")))


def run(
    lab: Lab, questions: list[evaluation.Question], entries: list[ManifestEntry], tmp_path: Path, split: str = "dev"
) -> tuple[uuid.UUID, Path, dict[str, Any]]:
    with Session(lab.engine) as session:
        return evaluation.run_evaluation(
            session, FakeEmbedder(lab.settings), questions, entries, split=split,
            modes=("vector", "lexical", "hybrid"), k=10, dataset_sha256="a" * 64, corpus_sha256="b" * 64,
            code_revision="test", artifacts_dir=tmp_path / "out",
        )  # fmt: skip


def test_a_run_is_scored_stored_and_written_as_an_artifact(lab: Lab, tmp_path: Path) -> None:
    entries = setup_corpus(lab, tmp_path)
    quote = "Sentence 1.0 on masters in masters cyclists older endurance athletes"
    questions = [evaluation.Question.model_validate(question(
        evidence=[{"corpus_id": "mcl-001", "page": 1, "quote": quote, "relevance": 2}],
        question="Sentence 1.0 on masters"))]  # fmt: skip

    run_id, artifact, summary = run(lab, questions, entries, tmp_path)

    assert summary["vector"]["recall@10"] == 1.0
    assert summary["vector"]["evidence_coverage@10"] == 1.0
    assert set(summary) == {"vector", "lexical", "hybrid"} and summary["hybrid"]["recall@10"] == 1.0
    saved = json.loads(artifact.read_text())
    assert "fusion" in saved["config"]["hybrid"]
    assert saved["evaluation_run_id"] == str(run_id) and saved["dataset_sha256"] == "a" * 64
    assert saved["questions"]["q900"]["vector"]["hits"][0]["corpus_id"] == "mcl-001"

    client = TestClient(create_app(lab.settings))
    assert client.get("/api/v1/evaluation-runs").json()["total"] == 1
    detail = client.get(f"/api/v1/evaluation-runs/{run_id}").json()
    assert detail["results"][0]["question_id"] == "q900" and "vector" in detail["metrics"]


def test_a_run_on_the_second_held_out_split_is_stored(lab: Lab, tmp_path: Path) -> None:
    entries = setup_corpus(lab, tmp_path)
    quote = "Sentence 1.0 on masters in masters cyclists older endurance athletes"
    questions = [evaluation.Question.model_validate(question(
        split="test2", evidence=[{"corpus_id": "mcl-001", "page": 1, "quote": quote, "relevance": 2}]))]  # fmt: skip

    run_id, _, summary = run(lab, questions, entries, tmp_path, split="test2")

    assert summary["vector"]["recall@10"] == 1.0
    client = TestClient(create_app(lab.settings))
    assert client.get(f"/api/v1/evaluation-runs/{run_id}").json()["split"] == "test2"


def test_a_quote_that_is_not_on_its_page_stops_the_run(lab: Lab, tmp_path: Path) -> None:
    entries = setup_corpus(lab, tmp_path)
    missing = {"corpus_id": "mcl-001", "page": 2, "quote": "This sentence is not in the paper at all.", "relevance": 2}
    wrong = [evaluation.Question.model_validate(question(evidence=[missing]))]
    with pytest.raises(evaluation.LabelError, match="quote not found"):
        run(lab, wrong, entries, tmp_path)
