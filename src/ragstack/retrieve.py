"""Retrieval: load the index once, embed the query, return ranked chunks."""

from __future__ import annotations

import threading
from pathlib import Path

from . import config, embed
from .store import SearchHit, VectorStore

_store: VectorStore | None = None
_store_dir: Path | None = None
_lock = threading.Lock()


def get_store(index_dir: Path | None = None, *, reload: bool = False) -> VectorStore:
    """Return the loaded VectorStore, caching it process-wide.

    The cache is keyed on index_dir, so pointing at a different index (as tests
    and multi-corpus setups do) reloads instead of silently serving the old one.
    """
    global _store, _store_dir
    target = Path(index_dir or config.INDEX_DIR)

    if reload or _store is None or _store_dir != target:
        with _lock:
            if reload or _store is None or _store_dir != target:
                _store = VectorStore.load(target)
                _store_dir = target
    return _store


def search(
    query: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    source_filter: str | None = None,
    index_dir: Path | None = None,
) -> list[SearchHit]:
    """Semantic search over the indexed corpus."""
    if not query or not query.strip():
        raise ValueError("query must not be empty")

    store = get_store(index_dir)
    return store.search(
        embed.embed_one(query),
        top_k=top_k,
        min_score=min_score,
        source_filter=source_filter,
    )


def format_context(hits: list[SearchHit]) -> str:
    """Render hits as a numbered, citable context block for the model.

    Each passage is tagged with the index the model should cite, so citations in
    the answer can be traced back to a specific chunk of a specific file.
    """
    if not hits:
        return "(no relevant passages found)"

    blocks = []
    for i, hit in enumerate(hits, start=1):
        blocks.append(
            f"[{i}] source: {hit.citation()} (similarity {hit.score:.3f})\n{hit.text}"
        )
    return "\n\n---\n\n".join(blocks)
