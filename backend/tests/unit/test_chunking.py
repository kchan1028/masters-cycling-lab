import re

import pytest

from masters_cycling_lab.domain.chunking import ChunkingConfig, Span, chunk_pages, rebuild_text, token_windows
from masters_cycling_lab.domain.extraction import ExtractedPage


def word_offsets(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def wordpiece_like_offsets(text: str) -> list[tuple[int, int]]:
    """Split words longer than four characters into pieces, like a subword tokenizer does."""
    offsets = []
    for match in re.finditer(r"\S+", text):
        for start in range(match.start(), match.end(), 4):
            offsets.append((start, min(start + 4, match.end())))
    return offsets


PAGE_TEXT = " ".join(f"word{n}" for n in range(1, 101))


def test_spans_rebuild_every_chunk_exactly() -> None:
    pages = [ExtractedPage(1, None, PAGE_TEXT), ExtractedPage(2, "ii", "Second page text.")]
    chunks = chunk_pages(pages, word_offsets, ChunkingConfig(max_tokens=30, overlap_tokens=5))

    page_texts = {p.page_number: p.text for p in pages}
    assert all(rebuild_text(chunk.spans, page_texts) == chunk.text for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert chunks[-1].spans == (Span(2, 0, len("Second page text.")),)


def test_windows_respect_the_token_limit_and_overlap() -> None:
    config = ChunkingConfig(max_tokens=30, overlap_tokens=5)
    windows = list(token_windows(word_offsets(PAGE_TEXT), config))

    assert all(count <= 30 for _, _, count in windows)
    first, second = PAGE_TEXT[windows[0][0] : windows[0][1]], PAGE_TEXT[windows[1][0] : windows[1][1]]
    assert first.split()[-5:] == second.split()[:5]
    assert PAGE_TEXT[windows[-1][0] : windows[-1][1]].endswith("word100")


def test_words_split_into_subword_tokens_are_never_cut() -> None:
    text = " ".join(["physiological"] * 40)
    for start, end, count in token_windows(
        wordpiece_like_offsets(text), ChunkingConfig(max_tokens=10, overlap_tokens=2)
    ):
        assert count <= 10
        assert all(word == "physiological" for word in text[start:end].split())


def test_a_word_longer_than_the_limit_is_cut_rather_than_looping_forever() -> None:
    text = "a" * 100
    windows = list(token_windows(wordpiece_like_offsets(text), ChunkingConfig(max_tokens=5, overlap_tokens=1)))
    assert windows[-1][1] == 100
    assert all(count <= 5 for _, _, count in windows)


def test_empty_pages_produce_no_chunks() -> None:
    pages = [ExtractedPage(1, None, ""), ExtractedPage(2, None, "Only text.")]
    chunks = chunk_pages(pages, word_offsets, ChunkingConfig(max_tokens=10, overlap_tokens=2))
    assert [chunk.spans[0].page_number for chunk in chunks] == [2]


def test_chunking_is_deterministic_and_its_config_hash_is_stable() -> None:
    pages = [ExtractedPage(1, None, PAGE_TEXT)]
    config = ChunkingConfig(max_tokens=25, overlap_tokens=4)
    assert chunk_pages(pages, word_offsets, config) == chunk_pages(pages, word_offsets, config)
    assert config.sha256() == ChunkingConfig(max_tokens=25, overlap_tokens=4).sha256()
    assert config.sha256() != ChunkingConfig(max_tokens=25, overlap_tokens=5).sha256()


@pytest.mark.parametrize("overlap", [0, 9])
def test_overlap_extremes_still_make_progress(overlap: int) -> None:
    windows = list(token_windows(word_offsets(PAGE_TEXT), ChunkingConfig(max_tokens=10, overlap_tokens=overlap)))
    starts = [start for start, _, _ in windows]
    assert starts == sorted(set(starts))
    assert PAGE_TEXT[windows[-1][0] : windows[-1][1]].endswith("word100")
