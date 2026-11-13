# Labelled questions

[`questions.jsonl`](questions.jsonl) holds the evaluation questions, one JSON object per line. It is version
controlled; evaluation runs only read it. Metrics and targets are in [docs/evaluation.md](../../docs/evaluation.md).

## Current set

74 questions in three splits:

- `dev`, 43 questions: for tuning and experiments.
- `test`, 11 questions: held out. Results on it have been reported three times, so it is no longer fresh.
- `test2`, 20 questions: held out, added on 2026-11-12 (q031 to q074 are split between `dev` and `test2`).
  Reported twice: the dataset v2 run, and one check of a reranker setting chosen on dev (not adopted). No setting
  has been chosen because of it.

| `question_type` | Count | What it tests |
|---|---|---|
| `direct` | 48 | One paper answers it |
| `synthesis` | 7 | The answer combines several papers |
| `population_mismatch` | 9 | Relevant evidence exists, but for another population (runners, young athletes) |
| `insufficient_evidence` | 6 | The corpus does not answer it; the system should say so |
| `out_of_scope` | 4 | Not a research question for this app (personal coaching, equipment) |

## Fields

| Field | Meaning |
|---|---|
| `id`, `split` | Stable ID (`q001`) and `dev` or `test` |
| `question` | The question as a user would ask it |
| `question_type`, `answerability` | See above; `answerability` is `answerable`, `partially_answerable`, `insufficient_evidence` or `out_of_scope` |
| `population_applicability` | Whether the evidence is about masters cyclists, and if not, how it differs |
| `expected_points`, `expected_limitations` | What a good answer says and which caveats it must mention |
| `document_relevance` | Graded judgments per corpus paper: **2** directly answers, **1** related or partial, **0** judged not relevant. A paper that is not listed was not judged |
| `evidence` | Gold passages: corpus paper, **physical** PDF page, the exact quotation, and its relevance (1 or 2) |
| `annotation` | Author, date, `review_status` (`provisional` or `reviewed`), the rationale, and once a person has reviewed it `reviewed_by`, `reviewed_on` and any `review_notes` |

Evidence is anchored to the paper (by manifest ID, which maps to the PDF's SHA-256), the physical page and the exact
text, not to chunk IDs, so labels keep working when chunking changes. Quotations are copied from the stored page
text, including line-break hyphenation such as `lit- tle`; matching ignores whitespace differences only.

## Review status

Every question here was drafted by Claude (an AI) on 2026-11-12 from the stored text of the papers. On 2026-11-13 KC
reviewed with `make review` and accepted unchanged 19 of the 20 `test2` questions (q033 was skipped) and 10 of the 43
`dev` questions (q001 to q015); the other 45 are still `provisional`. q001 to q030 were written in one pass. For q031 to q074, four agents each drafted questions from five
papers' stored text; the five questions without evidence (q070 to q074) were written after a text search of all 20
papers showed no paper covers their topic. All 44 drafts were checked mechanically (schema, every quotation on its
page, near-duplicates); one near-duplicate was dropped, one grade lowered, and questions on the same topic kept in
the same split. Splits alternate within each question type. For the provisional questions that means:

- The quotations are real: `make labels-check` proves each one appears on its stated page.
- The judgments are not independent human ground truth: which papers are relevant, the grades, the expected points
  and limitations are one model's reading.

## Reviewing labels

```bash
make review REVIEWER="Your Name"
```

With the stack running and the corpus ingested, this walks through every `provisional` question (add `SPLIT=dev` or
`SPLIT=test` to limit it). For each one it prints the question, expected points and limitations, the graded papers
with their titles, and every gold quotation inside its surrounding page text, with a link that opens the PDF at that
page. Then:

- **a**ccept: a person checked the quotations support the expected points, the grades are right, and no other paper
  in the corpus should have been graded. Sets `review_status: reviewed`, `reviewed_by` and `reviewed_on`.
- **n**ote: something is wrong. The note is stored in `review_notes` and the question stays `provisional`. Fix the
  fields by hand in `questions.jsonl`, run `make labels-check`, then review it again.
- **s**kip or **q**uit. Every verdict is written immediately, so stopping part way loses nothing.

Only the reviewed question's line changes, so `git diff` shows exactly what a review did. Review one question again
with `uv --directory backend run mcl review --reviewer "Your Name" --question q001`. Accepting is a person's
judgment; it must not be done by an AI or a script.

Do not change a `test` question's labels because of a result; fix only labelling errors, and say so in a note. Every
evaluation run records how many of its split's labels were reviewed, and the Evaluations page shows it.

## Rating answers

```bash
uv --directory backend run python ../research/evaluation/experiments/rate_answers.py "Your Name" ../artifacts/answers/answers-dev.json
```

Run it in a terminal on an answer run saved by `answer_run.py`. For each claim of each answer it prints the
question, the claim and the excerpts it cites, and asks whether those excerpts **s**upport the claim, support it only
**p**artly (the claim says more than they do), or do **n**ot support it, with an optional note. `k` skips the rest of
an answer and `q` quits. Ratings are saved after every claim to `answers-dev.ratings.json` next to the answers (in the
git-ignored `artifacts/`) and a later run resumes. Rate what the excerpts say, not what the paper says elsewhere, and
leave it to a person, as with labels.

## Dataset versions

Results are only comparable on the same questions and corpus. Each run stores the SHA-256 of both files; the
versions reported in [docs/evaluation.md](../../docs/evaluation.md) are:

| Version | `questions.jsonl` SHA-256 | `manifest.jsonl` SHA-256 | Frozen | Labels |
|---|---|---|---|---|
| v1 | `9b4564552f8e5b54…` | `e68d33b48785581c…` | 2026-11-12, commit `3294220` | 30 provisional, 0 reviewed |
| v2 | `2e64817a818cc966…` | `e68d33b48785581c…` | 2026-11-12, commit `bf821f8` | 74 provisional, 0 reviewed; adds `test2` |
| v3 | `8feb3b48f2228fdf…` | `e68d33b48785581c…` | 2026-11-13, commit `79dd4e2` | 19 reviewed (`test2`), 55 provisional; labels unchanged from v2 |
| v4 | `a928b3a4f8b8292b…` | `e68d33b48785581c…` | 2026-11-13, commit `a60a3b5` | 62 reviewed (all 43 `dev`, 19 `test2`), 12 provisional (11 `test`, q033); labels unchanged from v2 |
| v5 | `6d6b3e8009e4f373…` | `e68d33b48785581c…` | 2026-11-13, commit `977f0c7` | all 74 reviewed; labels unchanged from v2 |

Changing the file (including recording reviews) makes a new version. Add a row here when results are reported on
it. Split membership is fixed: questions never move between splits. `mcl evaluate --split test` (or `test2`) runs only
from a clean checkout, so every held-out result points at a commit.
