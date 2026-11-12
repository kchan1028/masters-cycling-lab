# Labelled questions

[`questions.jsonl`](questions.jsonl) holds the evaluation questions, one JSON object per line. It is version
controlled; evaluation runs only read it. Metrics and targets are in [docs/evaluation.md](../../docs/evaluation.md).

## Current set

30 questions: 19 `dev`, 11 `test` (held out, never used for tuning).

| `question_type` | Count | What it tests |
|---|---|---|
| `direct` | 18 | One paper answers it |
| `synthesis` | 3 | The answer combines several papers |
| `population_mismatch` | 4 | Relevant evidence exists, but for another population (runners, young athletes) |
| `insufficient_evidence` | 3 | The corpus does not answer it; the system should say so |
| `out_of_scope` | 2 | Not a research question for this app (personal coaching, equipment) |

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

Every question here was drafted by Claude (an AI) on 2026-11-12 from the stored text of the papers, and is marked
`provisional`. That means:

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

## Dataset versions

Results are only comparable on the same questions and corpus. Each run stores the SHA-256 of both files; the
versions reported in [docs/evaluation.md](../../docs/evaluation.md) are:

| Version | `questions.jsonl` SHA-256 | `manifest.jsonl` SHA-256 | Frozen | Labels |
|---|---|---|---|---|
| v1 | `9b4564552f8e5b54…` | `e68d33b48785581c…` | 2026-11-12, commit `3294220` | 30 provisional, 0 reviewed |

Changing the file (including recording reviews) makes a new version. Add a row here when results are reported on
it. Split membership is fixed: questions do not move between `dev` and `test`. `mcl evaluate --split test` runs only
from a clean checkout, so every held-out result points at a commit.
