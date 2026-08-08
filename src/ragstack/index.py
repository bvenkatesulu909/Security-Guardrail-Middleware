"""Index construction: docs/ -> chunks -> embeddings -> persisted vector store."""

from __future__ import annotations

import time
from pathlib import Path

from . import chunking, config, embed
from .store import VectorStore


def build_index(
    docs_dir: Path | None = None,
    index_dir: Path | None = None,
    *,
    show_progress: bool = True,
    verbose: bool = True,
) -> VectorStore:
    """Chunk every document under docs_dir, embed it, and persist the index."""
    docs_dir = Path(docs_dir or config.DOCS_DIR)
    index_dir = Path(index_dir or config.INDEX_DIR)

    if not docs_dir.exists():
        raise FileNotFoundError(
            f"Document directory {docs_dir} does not exist. Create it and add "
            f"some {', '.join(sorted(config.SUPPORTED_SUFFIXES))} files."
        )

    files = chunking.discover(docs_dir)
    if not files:
        raise ValueError(
            f"No indexable documents found in {docs_dir}. Supported types: "
            f"{', '.join(sorted(config.SUPPORTED_SUFFIXES))}"
        )

    if verbose:
        print(f"Reading {len(files)} document(s) from {docs_dir}")

    chunks = chunking.chunk_corpus(docs_dir)
    if not chunks:
        raise ValueError(f"Documents in {docs_dir} produced no text to index.")

    if verbose:
        print(f"Split into {len(chunks)} chunk(s). Embedding with {config.EMBED_MODEL} ...")

    started = time.perf_counter()
    vectors = embed.embed([c.text for c in chunks], show_progress=show_progress)
    elapsed = time.perf_counter() - started

    store = VectorStore.build(
        chunks,
        vectors,
        info={
            "embed_model": config.EMBED_MODEL,
            "dimension": int(vectors.shape[1]),
            "chunk_size": config.CHUNK_SIZE,
            "chunk_overlap": config.CHUNK_OVERLAP,
            "documents": len(files),
            "chunks": len(chunks),
            "docs_dir": str(docs_dir),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
    )
    store.save(index_dir)

    if verbose:
        print(
            f"Embedded {len(chunks)} chunk(s) in {elapsed:.1f}s "
            f"({vectors.shape[1]} dims). Index written to {index_dir}"
        )
    return store
