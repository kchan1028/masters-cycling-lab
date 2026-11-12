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
| `annotation` | Author, date, `review_status` (`provisional` or `reviewed`) and the rationale |

Evidence is anchored to the paper (by manifest ID, which maps to the PDF's SHA-256), the physical page and the exact
text, not to chunk IDs, so labels keep working when chunking changes. Quotations are copied from the stored page
text, including line-break hyphenation such as `lit- tle`; matching ignores whitespace differences only.

## Review status

Every question here was drafted by Claude (an AI) on 2026-11-12 from the stored text of the papers, and is marked
`provisional`. That means:

- The quotations are real: `make labels-check` proves each one appears on its stated page.
- The judgments are not independent human ground truth: which papers are relevant, the grades, the expected points
  and limitations are one model's reading.

To review a question: open the cited pages (`GET /api/v1/documents/{id}/pages/{n}` or the PDF), check the quotation
supports the expected points, check no other paper in the corpus should have been graded, adjust the fields, then set
`review_status` to `reviewed` and `author` to your name. Do not change a `test` question's labels because of a
result; fix only labelling errors, and note them in the rationale.
