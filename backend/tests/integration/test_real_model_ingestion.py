import pytest

from masters_cycling_lab.infrastructure.embeddings.sentence_transformers_adapter import SentenceTransformerEmbedder
from tests.integration.lab import Lab, sample_pdf

pytestmark = pytest.mark.model


def test_real_pdf_reaches_ready_with_the_real_model(lab: Lab, real_embedder: SentenceTransformerEmbedder) -> None:
    document_id = lab.upload(sample_pdf())
    claim = lab.claim()
    lab.runner(claim, embedder=real_embedder).run()

    assert lab.job(claim.job_id).status == "succeeded"
    [version] = lab.versions(document_id)
    assert version.status == "ready"
    assert (version.embedding_model_id, version.embedding_model_revision) == (
        "BAAI/bge-small-en-v1.5",
        "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
    )
