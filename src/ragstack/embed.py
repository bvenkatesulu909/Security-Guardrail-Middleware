"""Local embeddings via sentence-transformers — no API key, no network after the
first model download.

The model is loaded lazily and cached process-wide: importing this module is
cheap, so the CLI and MCP server start fast and only pay the ~2s load cost when
they actually embed something.
"""

from __future__ import annotations

import threading

import numpy as np

from . import config

_model = None
_lock = threading.Lock()


def get_model():
    """Load (once) and return the sentence-transformers model."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(config.EMBED_MODEL)
    return _model


def dimension() -> int:
    """Embedding width of the configured model."""
    return int(get_model().get_sentence_embedding_dimension())


def embed(texts: list[str], *, show_progress: bool = False) -> np.ndarray:
    """Embed a list of texts into an L2-normalised float32 matrix.

    Normalising here means cosine similarity is a plain dot product downstream.
    """
    if not texts:
        return np.zeros((0, dimension()), dtype=np.float32)

    vectors = get_model().encode(
        texts,
        batch_size=config.EMBED_BATCH_SIZE,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return np.asarray(vectors, dtype=np.float32)


def embed_one(text: str) -> np.ndarray:
    """Embed a single string, returning a 1-D vector."""
    return embed([text])[0]
