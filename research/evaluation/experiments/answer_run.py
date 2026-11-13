"""Ask every question of a split through the running app's answer API and save what came back.

With the stack up and an LLM configured:

    uv --directory backend run python ../research/evaluation/experiments/answer_run.py dev out.json

It sends every question to the configured provider, so it costs what the provider charges. Run it again with the same
output file to resume: questions that already got an answer are kept, the rest (errors included) are asked again.
Requests are spaced out so a free tier's per-minute limit is less likely to trip.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from masters_cycling_lab.application import corpus, evaluation

split = sys.argv[1]
out_path = sys.argv[2]
API = "http://127.0.0.1:8080/api/v1"
sha_to_corpus = {e.sha256: e.corpus_id for e in corpus.load_manifest(corpus.DEFAULT_MANIFEST)}
documents = json.load(urllib.request.urlopen(f"{API}/documents?limit=100", timeout=60))["items"]
doc_to_corpus = {d["id"]: sha_to_corpus.get(d["sha256"]) for d in documents}

PAUSE_SECONDS = 15
done = json.loads(Path(out_path).read_text()) if Path(out_path).exists() else []
rows = [r for r in done if r["answer"] is not None]
answered_ids = {r["id"] for r in rows}
for q in [q for q in evaluation.load_questions(evaluation.DEFAULT_QUESTIONS) if q.split == split]:
    if q.id in answered_ids:
        continue
    time.sleep(PAUSE_SECONDS)
    body = json.dumps({"question": q.question, "include_debug": False}).encode()
    request = urllib.request.Request(f"{API}/answers", data=body, headers={"Content-Type": "application/json"})
    started = time.time()
    answer, status, code = None, "no reply", None
    for _attempt in range(3):
        try:
            answer = json.load(urllib.request.urlopen(request, timeout=300))
            status, code = answer["status"], None
            break
        except urllib.error.HTTPError as error:
            answer, status = None, f"http {error.code}"
            try:
                code = json.loads(error.read() or b"{}").get("error", {}).get("code")
            except ValueError:  # a proxy error page instead of the API's JSON
                code = None
            if error.code not in (502, 503):
                break
            time.sleep(10)
        except Exception as error:  # noqa: BLE001 - record and move on
            status = type(error).__name__
    citations = [c for claim in (answer or {}).get("claims", []) for c in claim["citations"]]
    cited = sorted({doc_to_corpus.get(c["document_id"]) for c in citations} - {None})
    best = sorted(c for c, g in q.document_relevance.items() if g == 2)
    rows.append(
        {
            "id": q.id,
            "type": q.question_type,
            "answerability": q.answerability,
            "status": status,
            "error_code": code,
            "seconds": round(time.time() - started, 1),
            "claims": len((answer or {}).get("claims", [])),
            "cited": cited,
            "grade2": best,
            "judged": sorted(q.document_relevance),
            "cites_grade2": bool(set(cited) & set(best)),
            "answer": answer,
        }
    )
    r = rows[-1]
    print(f"{q.id} {q.question_type:12.12} {status:22} cited={cited} grade2={best} {r['seconds']}s", flush=True)
    with open(out_path, "w") as out:  # rewritten after every question, so a stopped run keeps what it has
        json.dump(sorted(rows, key=lambda row: row["id"]), out, indent=1)
