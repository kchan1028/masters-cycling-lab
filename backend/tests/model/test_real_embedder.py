"""Tests with the real pinned model. Opt-in (`make test-model`): the first run downloads about 130 MB."""

from pathlib import Path

import numpy as np
import pytest

from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.chunking import ChunkingConfig, chunk_pages, rebuild_text
from masters_cycling_lab.domain.extraction import ExtractedPage
from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import (
    ModelNotDownloaded,
    SentenceTransformerEmbedder,
)

pytestmark = pytest.mark.model

LONG_PAGE = " ".join(
    "Masters cyclists aged 50 to 70 completed twelve weeks of heavy strength training alongside endurance "
    "riding; peak power, VO2max and recovery markers were compared with age-matched controls."
    for _ in range(40)
)


def test_model_matches_the_pinned_configuration(real_embedder: SentenceTransformerEmbedder) -> None:
    assert real_embedder.dimension == 384
    assert real_embedder.max_tokens == 512
    modules = [type(module).__name__ for module in real_embedder.model]
    assert modules == ["Transformer", "Pooling", "Normalize"]


def test_a_missing_model_is_reported_instead_of_replaced(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, database_url="unused://", model_cache_dir=tmp_path)
    with pytest.raises(ModelNotDownloaded, match="make download-model"):
        SentenceTransformerEmbedder(settings)


def test_real_tokenizer_chunks_stay_under_the_limit_and_rebuild_exactly(
    real_embedder: SentenceTransformerEmbedder,
) -> None:
    page = ExtractedPage(1, None, LONG_PAGE)
    chunks = chunk_pages([page], real_embedder.token_offsets, ChunkingConfig(max_tokens=300, overlap_tokens=40))

    assert len(chunks) > 3
    for chunk in chunks:
        assert rebuild_text(chunk.spans, {1: page.text}) == chunk.text
        assert real_embedder.count_tokens(chunk.text) <= 302  # 300 text tokens plus [CLS] and [SEP]


def test_embeddings_are_unit_length_and_meaningful(real_embedder: SentenceTransformerEmbedder) -> None:
    vectors = real_embedder.embed_documents(
        [
            "Older cyclists needed more days to recover after hard interval sessions.",
            "Recovery after intense training was slower in masters endurance athletes.",
            "The tax code changed the depreciation schedule for commercial property.",
        ]
    )
    assert vectors.shape == (3, 384)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, rtol=1e-5)
    related, unrelated = float(vectors[0] @ vectors[1]), float(vectors[0] @ vectors[2])
    assert related > unrelated
