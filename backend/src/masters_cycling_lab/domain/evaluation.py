"""Retrieval metrics.

k always counts returned passages (chunks). Document-level metrics first reduce those passages to documents in order
of first appearance, so several chunks from one paper never count as several relevant studies.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceSpan:
    """A located piece of text: corpus document, physical page, and [start, end) in the stored page text."""

    document: str
    page: int
    start: int
    end: int

    def overlaps(self, other: "EvidenceSpan") -> bool:
        return (
            self.document == other.document
            and self.page == other.page
            and self.start < other.end
            and other.start < self.end
        )


def find_quote(page_text: str, quote: str) -> tuple[int, int] | None:
    """Where `quote` appears in `page_text`, ignoring differences in whitespace such as PDF line breaks."""
    words = quote.split()
    if not words:
        return None
    match = re.search(r"\s+".join(re.escape(word) for word in words), page_text)
    return (match.start(), match.end()) if match else None


def documents_in_order(chunk_documents: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(chunk_documents))


def recall(ranked_documents: Sequence[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    return len(set(ranked_documents) & relevant) / len(relevant)


def reciprocal_rank(ranked_documents: Sequence[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    for position, document in enumerate(ranked_documents, start=1):
        if document in relevant:
            return 1 / position
    return 0.0


def ndcg(ranked_documents: Sequence[str], grades: dict[str, int], k: int) -> float | None:
    """Graded: gain 2^grade - 1, so grade 2 counts three times as much as grade 1. Unjudged documents score 0.
    The ideal ranking puts the best-graded judged documents in the first k positions."""
    ideal = sorted((grade for grade in grades.values() if grade > 0), reverse=True)[:k]
    ideal_gain = discounted_gain(ideal)
    if ideal_gain == 0:
        return None
    return discounted_gain([grades.get(document, 0) for document in ranked_documents[:k]]) / ideal_gain


def discounted_gain(grades: Sequence[int]) -> float:
    return float(sum((2**grade - 1) / math.log2(position + 2) for position, grade in enumerate(grades)))


def span_coverage(retrieved: Sequence[EvidenceSpan], gold: Sequence[EvidenceSpan]) -> float | None:
    """Share of gold evidence passages that at least one retrieved chunk overlaps."""
    if not gold:
        return None
    return sum(any(span.overlaps(target) for span in retrieved) for target in gold) / len(gold)


def unjudged(ranked_documents: Sequence[str], judged: set[str]) -> int:
    return sum(document not in judged for document in ranked_documents)
