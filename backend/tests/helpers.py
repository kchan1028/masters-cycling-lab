"""Test-only stand-ins. Real application paths never use these."""

import hashlib
import re
from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pymupdf

from masters_cycling_lab.config import Settings


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
        encryption = pymupdf.PDF_ENCRYPT_AES_256  # type: ignore[attr-defined]  # missing from PyMuPDF's hints
        return bytes(document.tobytes(encryption=encryption, owner_pw=password, user_pw=password))
    return bytes(document.tobytes())


class FakeEmbedder:
    """Whitespace "tokens" and hash-based unit vectors: deterministic and instant."""

    def __init__(self, settings: Settings, on_embed: Callable[[int], None] | None = None) -> None:
        self.model_id = settings.embedding_model_id
        self.revision = settings.embedding_model_revision
        self.dimension = settings.embedding_dimension
        self.max_tokens = 512
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
