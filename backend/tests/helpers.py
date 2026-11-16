"""Test-only stand-ins. Real application paths never use these."""

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pymupdf

from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.ports import LanguageModelReply


def make_pdf(
    pages: list[str],
    *,
    title: str | None = None,
    roman_labels: bool = False,
    image_only_pages: tuple[int, ...] = (),
    password: str | None = None,
) -> bytes:
    """Build a small real PDF. `image_only_pages` are 1-based page numbers that get an image and no text."""
    document = pymupdf.open()
    for number, text in enumerate(pages, start=1):
        page = document.new_page()
        if number in image_only_pages:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), False)
            pixmap.clear_with(180)
            page.insert_image(pymupdf.Rect(72, 72, 300, 300), pixmap=pixmap)
        elif text:
            page.insert_textbox(pymupdf.Rect(50, 50, 560, 800), text, fontsize=9)
    if title:
        document.set_metadata({"title": title})
    if roman_labels:
        document.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1}])
    if password:
        encryption = pymupdf.PDF_ENCRYPT_AES_256
        return bytes(document.tobytes(encryption=encryption, owner_pw=password, user_pw=password))
    return bytes(document.tobytes())


class FakeEmbedder:
    """Whitespace "tokens" and hash-based unit vectors: deterministic and instant."""

    def __init__(self, settings: Settings, on_embed: Callable[[int], None] | None = None) -> None:
        self.model_id = settings.embedding_model_id
        self.revision = settings.embedding_model_revision
        self.dimension = settings.embedding_dimension
        self.max_tokens = 512
        self.query_instruction: str | None = None
        self.on_embed = on_embed
        self.calls = 0

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        return [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]

    def count_tokens(self, text: str) -> int:
        return len(self.token_offsets(text)) + 2

    def embed_documents(self, texts: list[str]) -> npt.NDArray[np.float32]:
        self.calls += 1
        if self.on_embed:
            self.on_embed(self.calls)
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
            rows.append(np.random.default_rng(seed).standard_normal(self.dimension))
        vectors = np.array(rows, dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def embed_query(self, text: str) -> npt.NDArray[np.float32]:
        # The same vector as a passage with identical text, so tests can aim a query at a known chunk.
        return np.asarray(self.embed_documents([text])[0], dtype=np.float32)


def manifest_entry(pdf: bytes, **overrides: object) -> dict[str, object]:
    """A valid corpus manifest line for `pdf`, saved as pdfs/paper.pdf, with any field overridden."""
    values: dict[str, object] = {
        "corpus_id": "mcl-001",
        "title": "Recovery in Masters Cyclists",
        "authors": ["Rider A"],
        "year": 2020,
        "citation": "J Test. 2020;1:1.",
        "doi": "10.1234/test.1",
        "pmcid": "PMC1",
        "pmid": 1,
        "landing_page_url": "https://example.org/paper",
        "download_url": "https://example.org/paper.pdf",
        "download_source": "test",
        "license": "CC BY",
        "license_source": "test",
        "access": "open_access",
        "redistribution": "allowed",
        "full_text": True,
        "retracted_at_acquisition": False,
        "file": "pdfs/paper.pdf",
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "bytes": len(pdf),
        "acquired_on": "2026-11-12",
        "bibliographic_source": "test",
        "population_relevance": "masters_cyclists",
        "population": "test riders",
        "age_range": "50-70",
        "sport": "cycling",
        "study_design": "test",
        "topics": ["recovery"],
        "description_source": "test",
        "description_review_status": "provisional",
    }
    values.update(overrides)
    return values


def write_manifest(folder: Path, *entries: dict[str, object]) -> Path:
    path = folder / "manifest.jsonl"
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    return path


class FakeLanguageModel:
    """Replies with scripted texts in order and records every request, so tests can check what was sent."""

    def __init__(self, *replies: str, error: Exception | None = None) -> None:
        self.model = "test-model"
        self.replies = list(replies)
        self.error = error
        self.requests: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], max_tokens: int) -> LanguageModelReply:
        self.requests.append([dict(message) for message in messages])
        if self.error:
            raise self.error
        return LanguageModelReply(text=self.replies.pop(0), model=self.model, usage={"total_tokens": 100})
