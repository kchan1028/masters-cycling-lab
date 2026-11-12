from pathlib import Path

from huggingface_hub import try_to_load_from_cache

from masters_cycling_lab.config import Settings


def model_files_present(settings: Settings, cache_dir: Path | None = None) -> bool:
    """True when the pinned revision's modules.json is in the local cache. Cheap: doesn't load the model.

    Without modules.json, sentence-transformers quietly builds a different model (mean pooling instead of bge's CLS
    pooling) that still returns 384 numbers, so this file is the one to check.
    """
    cached = try_to_load_from_cache(
        settings.embedding_model_id,
        "modules.json",
        cache_dir=cache_dir or settings.model_cache_dir,
        revision=settings.embedding_model_revision,
    )
    return isinstance(cached, str)
