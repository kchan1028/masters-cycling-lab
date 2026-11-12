from pathlib import Path

import numpy as np
import numpy.typing as npt
from huggingface_hub import try_to_load_from_cache
from sentence_transformers import SentenceTransformer

from masters_cycling_lab.config import Settings


class ModelNotDownloaded(Exception):
    pass


class SentenceTransformerEmbedder:
    """The pinned embedding model, loaded once. Loading takes seconds, so build one per process and reuse it."""

    def __init__(self, settings: Settings, *, allow_download: bool = False) -> None:
        self.model_id = settings.embedding_model_id
        self.revision = settings.embedding_model_revision
        self.batch_size = settings.embedding_batch_size
        cache_dir = settings.model_cache_dir
        missing = ModelNotDownloaded(
            f"{self.model_id}@{self.revision[:7]} is not in {cache_dir}. Run `make download-model`."
        )
        # Without modules.json, sentence-transformers quietly builds a different model (mean pooling instead of
        # bge's CLS pooling) that still returns 384 numbers. Refuse to load a partial download.
        if not allow_download and not self.has_model_config(cache_dir):
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
        if not self.has_model_config(cache_dir):
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

    def has_model_config(self, cache_dir: Path) -> bool:
        cached = try_to_load_from_cache(self.model_id, "modules.json", cache_dir=cache_dir, revision=self.revision)
        return isinstance(cached, str)

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        encoded = self.model.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)
        return [(int(start), int(end)) for start, end in encoded["offset_mapping"]]

    def count_tokens(self, text: str) -> int:
        return len(self.model.tokenizer(text, add_special_tokens=True, verbose=False)["input_ids"])

    def embed_documents(self, texts: list[str]) -> npt.NDArray[np.float32]:
        # Passages get no instruction prefix; only queries do (bge's recommended setup).
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)
