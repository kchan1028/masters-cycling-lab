"""Interfaces for the slow or external parts that tests replace with simple fakes."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from masters_cycling_lab.domain.extraction import ExtractedPdf

# extract_pdf(path, max_pages) -> ExtractedPdf, raising IngestionProblem for PDFs that can't be indexed.
PdfExtractor = Callable[[Path, int], ExtractedPdf]


class Embedder(Protocol):
    model_id: str
    revision: str
    dimension: int
    max_tokens: int  # the model's input limit, including its special tokens
    query_instruction: str | None  # prefix added to queries (not passages), if the model wants one

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        """Character range of each token, without special tokens."""
        ...

    def count_tokens(self, text: str) -> int:
        """Tokens the model will see for this text, including special tokens."""
        ...

    def embed_documents(self, texts: list[str]) -> npt.NDArray[np.float32]:
        """One unit-length vector per text."""
        ...

    def embed_query(self, text: str) -> npt.NDArray[np.float32]:
        """A unit-length vector for a search query, with any query-side instruction the model expects."""
        ...


@dataclass(frozen=True)
class LanguageModelReply:
    text: str
    model: str
    # Token counts exactly as the provider reported them. None when it reported nothing; never estimated here.
    usage: dict[str, int] | None


class ProviderError(Exception):
    """The language model provider failed (unreachable, timed out, refused, or replied in an unusable shape)."""


class LanguageModel(Protocol):
    model: str

    def complete(self, messages: list[dict[str, str]], max_tokens: int) -> LanguageModelReply: ...
