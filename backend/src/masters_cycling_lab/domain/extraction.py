"""Extracted PDF pages and the conservative text cleanup applied before chunking."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace


class IngestionProblem(Exception):
    """A document that can't be indexed as it is (encrypted, scanned, corrupt...). Retrying won't help."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int  # physical page in the PDF, starting at 1
    label: str | None  # printed page label ("iv", "S12") when the PDF defines one
    text: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedPdf:
    pages: tuple[ExtractedPage, ...]
    title: str | None  # from the PDF's own metadata, so unverified
    extractor: str
    extractor_version: str


CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def normalize_text(text: str) -> str:
    """NFC, Unix line endings, no control characters, no trailing spaces, at most one blank line in a row."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_CHARS.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# Running headers and footers only make sense to detect when there are enough pages to see the repetition.
MIN_PAGES_FOR_EDGE_CLEANUP = 4


def edge_key(line: str) -> str:
    # Page numbers change from page to page, so compare lines with digits masked.
    return re.sub(r"\d+", "#", line.strip().lower())


def remove_repeated_edge_lines(pages: list[ExtractedPage]) -> list[ExtractedPage]:
    """Drop running headers, footers and page numbers.

    Deliberately conservative: only a page's first and last line are candidates, a line must repeat (ignoring
    digits) on at least half of the pages and on at least three, and every removal is recorded as a page warning.
    """
    if len(pages) < MIN_PAGES_FOR_EDGE_CLEANUP:
        return pages

    lines_by_page = [page.text.split("\n") if page.text else [] for page in pages]
    threshold = max(3, (len(pages) + 1) // 2)
    first_counts = Counter(edge_key(lines[0]) for lines in lines_by_page if lines)
    last_counts = Counter(edge_key(lines[-1]) for lines in lines_by_page if lines)
    repeated_first = {key for key, count in first_counts.items() if key and count >= threshold}
    repeated_last = {key for key, count in last_counts.items() if key and count >= threshold}

    cleaned = []
    for page, lines in zip(pages, lines_by_page, strict=True):
        warnings = list(page.warnings)
        if lines and edge_key(lines[0]) in repeated_first:
            warnings.append(f"Removed repeated header line: {lines.pop(0)[:80]!r}")
        if lines and edge_key(lines[-1]) in repeated_last:
            warnings.append(f"Removed repeated footer line: {lines.pop()[:80]!r}")
        cleaned.append(replace(page, text="\n".join(lines).strip(), warnings=tuple(warnings)))
    return cleaned
