import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from masters_cycling_lab.application.evaluation import (
    DEFAULT_QUESTIONS,
    LabelError,
    Question,
    load_questions,
    record_review,
    review_counts,
)
from masters_cycling_lab.domain import evaluation as m
from masters_cycling_lab.domain.evaluation import EvidenceSpan


def test_quotes_are_found_despite_line_breaks() -> None:
    page = "Results.\nMasters cyclists recovered\n  as fast as younger riders."
    start, end = m.find_quote(page, "Masters cyclists recovered as fast as younger riders.") or (0, 0)
    assert page[start:end].split() == ["Masters", "cyclists", "recovered", "as", "fast", "as", "younger", "riders."]
    assert m.find_quote(page, "recovered faster") is None


def test_documents_count_once_in_order_of_first_appearance() -> None:
    assert m.documents_in_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_recall_mrr_and_unjudged() -> None:
    ranked = ["x", "a", "y"]
    assert m.recall(ranked, {"a", "b"}) == 0.5
    assert m.reciprocal_rank(ranked, {"a", "b"}) == 0.5
    assert m.reciprocal_rank(ranked, {"b"}) == 0.0
    assert m.recall(ranked, set()) is None
    assert m.unjudged(ranked, {"a", "x"}) == 1


def test_ndcg_is_one_for_the_ideal_order_and_lower_otherwise() -> None:
    grades = {"a": 2, "b": 1, "c": 0}
    assert m.ndcg(["a", "b"], grades, k=10) == pytest.approx(1.0)
    assert m.ndcg(["b", "a"], grades, k=10) == pytest.approx((1 + 3 / 1.585) / (3 + 1 / 1.585), rel=1e-3)
    assert (m.ndcg(["a"], grades, k=10) or 1.0) < 1.0  # a relevant document was missed
    assert m.ndcg(["z"], {"z": 0}, k=10) is None  # nothing relevant to find


def test_span_coverage_needs_the_same_document_page_and_overlap() -> None:
    gold = [EvidenceSpan("mcl-001", 2, 100, 200), EvidenceSpan("mcl-002", 1, 0, 50)]
    retrieved = [EvidenceSpan("mcl-001", 2, 150, 400), EvidenceSpan("mcl-002", 2, 0, 50)]
    assert m.span_coverage(retrieved, gold) == 0.5
    assert m.span_coverage(retrieved, []) is None


def test_the_committed_questions_are_valid_and_balanced() -> None:
    questions = load_questions(DEFAULT_QUESTIONS)
    assert len(questions) >= 25
    assert {"dev", "test"} <= {q.split for q in questions}
    types = {q.question_type for q in questions}
    assert types == {"direct", "synthesis", "population_mismatch", "insufficient_evidence", "out_of_scope"}


def question(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": "q900",
        "split": "dev",
        "question": "Does it work?",
        "question_type": "direct",
        "answerability": "answerable",
        "population_applicability": "masters_cyclists",
        "expected_points": [],
        "expected_limitations": [],
        "document_relevance": {"mcl-001": 2},
        "evidence": [{"corpus_id": "mcl-001", "page": 1, "quote": "A sufficiently long quotation.", "relevance": 2}],
        "annotation": {"author": "t", "date": "2026-11-12", "review_status": "provisional", "rationale": "t"},
    }
    values.update(overrides)
    return values


def test_evidence_must_come_from_a_relevant_document() -> None:
    with pytest.raises(ValidationError, match="document_relevance"):
        Question.model_validate(question(document_relevance={}))


def test_answerable_questions_need_evidence() -> None:
    with pytest.raises(ValidationError, match="gold evidence"):
        Question.model_validate(question(evidence=[]))


def test_a_reviewed_question_names_its_reviewer() -> None:
    annotation = {"author": "t", "date": "2026-11-12", "review_status": "reviewed", "rationale": "t"}
    with pytest.raises(ValidationError, match="reviewed_by"):
        Question.model_validate(question(annotation=annotation))


def write_questions(path: Path) -> list[str]:
    lines = [json.dumps(question(id=qid, question=f"Question {qid} – with a dash?"), ensure_ascii=False)
             for qid in ("q901", "q902")]  # fmt: skip
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def test_recording_a_review_changes_only_that_question(tmp_path: Path) -> None:
    path = tmp_path / "questions.jsonl"
    original = write_questions(path)

    record_review(path, "q902", reviewer="Pat", reviewed=True, note="Grades checked.", on=date(2026, 11, 13))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == original[0]
    annotation = json.loads(lines[1])["annotation"]
    assert annotation["review_status"] == "reviewed"
    assert annotation["reviewed_by"] == "Pat"
    assert annotation["reviewed_on"] == "2026-11-13"
    assert annotation["review_notes"] == ["2026-11-13 Pat: Grades checked."]
    assert review_counts(load_questions(path)) == {"reviewed": 1, "provisional": 1}


def test_a_note_alone_keeps_the_question_provisional(tmp_path: Path) -> None:
    path = tmp_path / "questions.jsonl"
    write_questions(path)

    record_review(
        path, "q901", reviewer="Pat", reviewed=False, note="mcl-004 should be graded 1.", on=date(2026, 11, 13)
    )
    record_review(path, "q901", reviewer="Sam", reviewed=False, note="Agreed.", on=date(2026, 11, 14))

    annotation = load_questions(path)[0].annotation
    assert annotation.review_status == "provisional"
    assert annotation.review_notes == ["2026-11-13 Pat: mcl-004 should be graded 1.", "2026-11-14 Sam: Agreed."]


def test_reviewing_an_unknown_question_fails(tmp_path: Path) -> None:
    path = tmp_path / "questions.jsonl"
    write_questions(path)
    with pytest.raises(LabelError, match="q999"):
        record_review(path, "q999", reviewer="Pat", reviewed=True, note=None, on=date(2026, 11, 13))
