"""Embedding backends for the Chroma retriever (all heavy imports are lazy).

Two interchangeable backends implement the :class:`Embedder` protocol:

* :class:`FastEmbedEmbedder` (default): ``fastembed`` (ONNX runtime) with
  ``BAAI/bge-small-en-v1.5``. Small, no torch needed. The model cache lives in
  a persistent, non-temp directory (``FASTEMBED_CACHE_PATH`` or
  ``~/.cache/uds_assistant/fastembed``); if it is empty but fastembed's old
  default temp cache already holds the model, that copy is reused.
* :class:`SentenceTransformerEmbedder`: optional path
  (``EMBEDDER=sentence-transformers``); imports ``sentence_transformers`` only
  when instantiated.
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


def fastembed_available() -> bool:
    """True if ``fastembed`` is importable."""
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def sentence_transformers_available() -> bool:
    """True if ``sentence_transformers`` is importable."""
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


class FastEmbedEmbedder:
    """``fastembed.TextEmbedding`` wrapper (default backend)."""

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


class SentenceTransformerEmbedder:
    """Optional ``sentence-transformers`` backend; never imported unless selected."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        from sentence_transformers import SentenceTransformer

        self.name = f"sentence-transformers:{model_name}"
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` (one vector each)."""
        return self._model.encode(texts, normalize_embeddings=True).tolist()


def embedder_available(backend: str) -> bool:
    """Whether the package for the named embedder backend is importable."""
    if backend == "sentence-transformers":
        return sentence_transformers_available()
    return fastembed_available()


def get_embedder(backend: str = "fastembed") -> Embedder:
    """Instantiate the named embedder backend."""
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder()
    return FastEmbedEmbedder()
