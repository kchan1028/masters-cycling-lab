"""Summarise an answer run saved by answer_run.py: abstention and whether citations point at the gold evidence.

    uv --directory backend run python ../research/evaluation/experiments/answer_report.py ../artifacts/answers/x.json

Needs the stack up only to map document ids to corpus ids. No model is called. A citation "hits a gold page" when it
cites a page that holds one of the question's gold quotations; that is a page-level check, not a reading of whether
the passage supports the claim, which still needs a person.
"""

import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from masters_cycling_lab.application import corpus, evaluation

API = "http://127.0.0.1:8080/api/v1"
NO_ANSWER = ("insufficient_evidence", "out_of_scope")


def main() -> None:
    rows = json.loads(Path(sys.argv[1]).read_text())
    questions = {q.id: q for q in evaluation.load_questions(evaluation.DEFAULT_QUESTIONS)}
    sha_to_corpus = {e.sha256: e.corpus_id for e in corpus.load_manifest(corpus.DEFAULT_MANIFEST)}
    documents = json.load(urllib.request.urlopen(f"{API}/documents?limit=100", timeout=60))["items"]
    doc_to_corpus = {d["id"]: sha_to_corpus.get(d["sha256"]) for d in documents}

    replied = [r for r in rows if r["answer"] is not None]
    errors = len(rows) - len(replied)
    print(f"{len(rows)} questions asked, {len(replied)} replies, {errors} errors (asked again on resume)")
    for (answerability, status), count in sorted(Counter((r["answerability"], r["status"]) for r in replied).items()):
        print(f"  {answerability:22} {status:22} {count}")

    answerable = [r for r in replied if r["answerability"] not in NO_ANSWER]
    answered = [r for r in answerable if r["status"] == "answered"]
    with_gold_page = 0
    print("\nPer answered question (claims, cites a grade-2 paper, citations on a gold page / citations):")
    for r in answered:
        gold_pages = {(e.corpus_id, e.page) for e in questions[r["id"]].evidence}
        cited_pages = [
            (doc_to_corpus.get(c["document_id"]), page)
            for claim in r["answer"]["claims"]
            for c in claim["citations"]
            for page in c["page_numbers"]
        ]
        on_gold = sum(page in gold_pages for page in cited_pages)
        with_gold_page += on_gold > 0
        grade2 = "yes" if r["cites_grade2"] else "no"
        print(f"  {r['id']}  {r['claims']} claims  grade-2 {grade2:3}  {on_gold}/{len(cited_pages)}")

    missed = [r["id"] for r in answerable if r["status"] != "answered"]
    print(
        f"\nAnswerable: {len(answered)}/{len(answerable)} answered, {sum(r['cites_grade2'] for r in answered)} citing "
        f"a grade-2 paper, {with_gold_page} citing a gold page; false abstentions: {', '.join(missed) or 'none'}"
    )
    no_answer = [r for r in replied if r["answerability"] in NO_ANSWER]
    wrongly_answered = [r["id"] for r in no_answer if r["status"] == "answered"]
    print(
        f"No evidence / out of scope: {len(no_answer) - len(wrongly_answered)}/{len(no_answer)} abstained; "
        f"answered anyway: {', '.join(wrongly_answered) or 'none'}"
    )


if __name__ == "__main__":
    main()
