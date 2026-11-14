"""The pinned embedding model (bge-small-en-v1.5 by default), run on the CPU with sentence-transformers."""

import numpy as np
import numpy.typing as npt
from sentence_transformers import SentenceTransformer

from masters_cycling_lab.config import Settings
from masters_cycling_lab.infrastructure.embeddings.model_cache import model_files_present

# bge's recommended instruction for short queries that search longer passages. Passages get no prefix.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class ModelNotDownloaded(Exception):
    """The pinned model revision is not in the local cache. `make download-model` fixes it."""

    pass


class SentenceTransformerEmbedder:
    """The pinned embedding model, loaded once. Loading takes seconds, so build one per process and reuse it."""

    def __init__(self, settings: Settings, *, allow_download: bool = False) -> None:
        self.model_id = settings.embedding_model_id
        self.revision = settings.embedding_model_revision
        self.batch_size = settings.embedding_batch_size
        self.query_instruction: str | None = QUERY_INSTRUCTION
        cache_dir = settings.model_cache_dir
        missing = ModelNotDownloaded(
            f"{self.model_id}@{self.revision[:7]} is not in {cache_dir}. Run `make download-model`."
        )
        # Refuse a partial download rather than let sentence-transformers fall back to a different model.
        if not allow_download and not model_files_present(settings, cache_dir):
            raise missing
        try:
            self.model = SentenceTransformer(
                self.model_id,
                revision=self.revision,
                cache_folder=str(cache_dir),
                device="cpu",
                local_files_only=not allow_download,
            )
        except OSError as exc:
            raise missing from exc
        if not model_files_present(settings, cache_dir):
            raise missing

        dimension = self.model.get_embedding_dimension()
        max_tokens = self.model.get_max_seq_length()
        if dimension is None or max_tokens is None:
            raise RuntimeError(f"{self.model_id} does not report its output dimension or input length.")
        self.dimension: int = dimension
        self.max_tokens: int = max_tokens
        if self.dimension != settings.embedding_dimension:
            raise RuntimeError(
                f"{self.model_id} produces {self.dimension}-dimensional vectors, "
                f"but EMBEDDING_DIMENSION is {settings.embedding_dimension}."
            )

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        """Character range of each token, without special tokens. Chunking cuts on these."""
        encoded = self.model.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)
        return [(int(start), int(end)) for start, end in encoded["offset_mapping"]]

    def count_tokens(self, text: str) -> int:
        """Tokens the model will see for this text, including [CLS] and [SEP]."""
        return len(self.model.tokenizer(text, add_special_tokens=True, verbose=False)["input_ids"])

    def embed_documents(self, texts: list[str]) -> npt.NDArray[np.float32]:
        """Unit-length vectors for passages, computed in batches of EMBEDDING_BATCH_SIZE."""
        # Passages get no instruction prefix; only queries do (bge's recommended setup).
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def embed_query(self, text: str) -> npt.NDArray[np.float32]:
        """A unit-length vector for a search query, with bge's query instruction in front."""
        vector = self.model.encode(
            [text],
            prompt=self.query_instruction,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
        return np.asarray(vector, dtype=np.float32)
