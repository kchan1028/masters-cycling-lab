"""Split page text into overlapping, token-limited chunks that point back to exact page offsets."""

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from masters_cycling_lab.domain.extraction import ExtractedPage

TokenOffsets = Callable[[str], list[tuple[int, int]]]


@dataclass(frozen=True)
class ChunkingConfig:
    max_tokens: int
    overlap_tokens: int
    # Bump when the algorithm changes, so old and new index versions are never mistaken for each other.
    strategy: str = "page_token_window_v1"

    def as_dict(self) -> dict[str, object]:
        return {"strategy": self.strategy, "max_tokens": self.max_tokens, "overlap_tokens": self.overlap_tokens}

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Span:
    """Half-open range [start, end) in one stored page's text. `separator` goes in front when rebuilding."""

    page_number: int
    start: int
    end: int
    separator: str = ""


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    text: str
    token_count: int  # tokens of text only, without the model's special tokens
    spans: tuple[Span, ...]


def chunk_pages(
    pages: Sequence[ExtractedPage], token_offsets: TokenOffsets, config: ChunkingConfig
) -> list[ChunkDraft]:
    """Chunks never cross a page boundary. That keeps every citation on one page, at the cost of splitting
    sentences that continue onto the next page."""
    chunks: list[ChunkDraft] = []
    for page in pages:
        if not page.text:
            continue
        for start, end, token_count in token_windows(token_offsets(page.text), config):
            span = Span(page.page_number, start, end)
            chunks.append(ChunkDraft(len(chunks), page.text[start:end], token_count, (span,)))
    return chunks


def token_windows(offsets: list[tuple[int, int]], config: ChunkingConfig) -> Iterator[tuple[int, int, int]]:
    """Yield (char_start, char_end, token_count) windows of at most max_tokens, never cutting a word in half.

    `offsets` are the character ranges of the model tokenizer's tokens. A token starts a new word when there is a
    gap (whitespace) between it and the previous token.
    """
    count = len(offsets)
    if count == 0:
        return
    starts_word = [i == 0 or offsets[i][0] > offsets[i - 1][1] for i in range(count)]

    start = 0
    while True:
        end = min(start + config.max_tokens, count)
        if end < count:
            # Step back to the start of the word the window would otherwise cut through.
            cut = end
            while cut > start + 1 and not starts_word[cut]:
                cut -= 1
            if starts_word[cut]:
                end = cut
        yield offsets[start][0], offsets[end - 1][1], end - start
        if end == count:
            return

        next_start = end - config.overlap_tokens
        while next_start > start and not starts_word[next_start]:
            next_start -= 1
        start = next_start if next_start > start else end


def rebuild_text(spans: Sequence[Span], page_texts: Mapping[int, str]) -> str:
    return "".join(span.separator + page_texts[span.page_number][span.start : span.end] for span in spans)
