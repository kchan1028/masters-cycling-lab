"""Rate whether the passages an answer cites support each of its claims, one claim at a time.

    uv --directory backend run python ../research/evaluation/experiments/rate_answers.py KC ../artifacts/answers/x.json

Reads an answer run saved by answer_run.py and writes the ratings next to it (x.ratings.json, keyed by query run and
claim number), after every claim, so quitting keeps what was rated and the next run resumes. No database or model is
needed. Ratings: s = the cited passages support the claim, p = partly (the claim says more than they do), n = not
supported. A summary of the ratings so far is printed at the end.
"""

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

RATINGS = {"s": "supported", "p": "partly", "n": "not_supported"}


def ask(prompt: str, choices: tuple[str, ...]) -> str:
    answer = ""
    while answer not in choices:  # an empty or mistyped answer asks again
        answer = input(prompt).strip().lower()
    return answer


def main() -> None:
    rater, answers_path = sys.argv[1], Path(sys.argv[2])
    ratings_path = answers_path.with_suffix(".ratings.json")
    ratings = json.loads(ratings_path.read_text()) if ratings_path.exists() else {}
    if not sys.stdin.isatty():
        raise SystemExit("Rating needs an interactive terminal.")
    answered = [row for row in json.loads(answers_path.read_text()) if row["status"] == "answered"]

    try:
        for row in answered:
            answer = row["answer"]
            rated = ratings.setdefault(answer["query_run_id"], {})
            for number, claim in enumerate(answer["claims"], start=1):
                if str(number) in rated:
                    continue
                print(f"\n=== {row['id']}, claim {number} of {len(answer['claims'])} ===")
                print(f"Question: {answer['question']}")
                print(f"\nClaim: {claim['text']}")
                for citation in claim["citations"]:
                    # A page without a printed label falls back to its page number in the PDF.
                    labels = zip(citation["page_labels"], citation["page_numbers"], strict=True)
                    pages = ", ".join(label or str(number) for label, number in labels)
                    print(f"\n  [{citation['evidence_id']}] {citation['document_title']}, page {pages}")
                    print("  " + citation["excerpt"].replace("\n", "\n  "))
                prompt = "\n[s]upported, [p]artly, [n]ot supported, [k] skip answer, [q]uit: "
                choice = ask(prompt, (*RATINGS, "k", "q"))
                if choice == "q":
                    return
                if choice == "k":
                    break
                note = input("Note (optional): ").strip() or None
                rated[str(number)] = {"rating": RATINGS[choice], "note": note, "rater": rater, "on": str(date.today())}
                ratings_path.write_text(json.dumps(ratings, indent=1))
    except (EOFError, KeyboardInterrupt):
        print("\nStopped; every rating so far is saved.")
    finally:
        counts = Counter(r["rating"] for claims in ratings.values() for r in claims.values())
        total = sum(counts.values())
        print(f"\n{total} claims rated: " + ", ".join(f"{counts[name]} {name}" for name in RATINGS.values()))


if __name__ == "__main__":
    main()
