"""BGE embeddings via fastembed (ONNX runtime, no torch); heavy imports are lazy.

Model: ``BAAI/bge-small-en-v1.5``. The model cache lives in a persistent, non-temp directory
(``FASTEMBED_CACHE_PATH`` or ``~/.cache/uds_assistant/fastembed``); if it is empty but
fastembed's old default temp cache already holds the model, that copy is reused.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"
FASTEMBED_CACHE_ENV = "FASTEMBED_CACHE_PATH"


class Embedder(Protocol):
    """Turns texts into dense vectors."""

    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...


def default_fastembed_cache_dir() -> Path:
    """Persistent cache dir: ``$FASTEMBED_CACHE_PATH`` or ``~/.cache/uds_assistant/fastembed``."""
    env = os.environ.get(FASTEMBED_CACHE_ENV)
    if env:
        return Path(env)
    return Path.home() / ".cache" / "uds_assistant" / "fastembed"


def _seed_cache_from_temp(cache_dir: Path) -> None:
    """Copy model dirs from fastembed's legacy temp cache into ``cache_dir`` if it has none."""
    if any(cache_dir.glob("models--*")):
        return
    legacy = Path(tempfile.gettempdir()) / "fastembed_cache"
    if not legacy.is_dir():
        return
    for model_dir in legacy.glob("models--*"):
        if model_dir.is_dir():
            shutil.copytree(model_dir, cache_dir / model_dir.name, dirs_exist_ok=True)


class FastEmbedEmbedder:
    """``fastembed.TextEmbedding`` wrapper."""

    def __init__(
        self, model_name: str = DEFAULT_MODEL_NAME, cache_dir: str | Path | None = None
    ) -> None:
        from fastembed import TextEmbedding

        cache = Path(cache_dir) if cache_dir is not None else default_fastembed_cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        _seed_cache_from_temp(cache)
        self.name = f"fastembed:{model_name}"
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache))

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` (one vector each)."""
        return [[float(x) for x in vec] for vec in self._model.embed(texts)]
