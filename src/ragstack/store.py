"""A small on-disk vector store: one .npz for the matrix, one .json for metadata.

Deliberately dependency-free beyond numpy. Exact (brute-force) cosine search is
instant well past 100k chunks, which is far more than a personal/team corpus
needs, and it keeps the whole index inspectable and diffable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config
from .chunking import Chunk

VECTORS_FILE = "vectors.npz"
META_FILE = "meta.json"
SCHEMA_VERSION = 1


@dataclass
class SearchHit:
    """A retrieved chunk and how well it matched."""

    score: float
    text: str
    source: str
    ordinal: int
    id: str

    def citation(self) -> str:
        return f"{self.source}#chunk{self.ordinal}"


class VectorStore:
    """Persisted embeddings + chunk metadata."""

    def __init__(self, vectors: np.ndarray, chunks: list[dict], info: dict | None = None):
        if len(vectors) != len(chunks):
            raise ValueError(
                f"vector/chunk count mismatch: {len(vectors)} vectors, {len(chunks)} chunks"
            )
        self.vectors = vectors.astype(np.float32, copy=False)
        self.chunks = chunks
        self.info = info or {}

    # --- construction --------------------------------------------------------

    @classmethod
    def build(cls, chunks: list[Chunk], vectors: np.ndarray, info: dict | None = None):
        payload = [
            {
                "id": c.id,
                "text": c.text,
                "source": c.source,
                "ordinal": c.ordinal,
                "meta": c.meta,
            }
            for c in chunks
        ]
        return cls(vectors, payload, info)

    # --- persistence ---------------------------------------------------------

    def save(self, index_dir: Path | None = None) -> Path:
        index_dir = Path(index_dir or config.INDEX_DIR)
        index_dir.mkdir(parents=True, exist_ok=True)

        np.savez_compressed(index_dir / VECTORS_FILE, vectors=self.vectors)
        (index_dir / META_FILE).write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "info": self.info,
                    "chunks": self.chunks,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return index_dir

    @classmethod
    def load(cls, index_dir: Path | None = None) -> "VectorStore":
        index_dir = Path(index_dir or config.INDEX_DIR)
        vectors_path = index_dir / VECTORS_FILE
        meta_path = index_dir / META_FILE

        if not vectors_path.exists() or not meta_path.exists():
            raise FileNotFoundError(
                f"No index at {index_dir}. Build one first:  ragstack index"
            )

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        version = meta.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"Index at {index_dir} uses schema v{version}, this build expects "
                f"v{SCHEMA_VERSION}. Rebuild with:  ragstack index --rebuild"
            )

        with np.load(vectors_path) as data:
            vectors = data["vectors"]

        return cls(vectors, meta["chunks"], meta.get("info", {}))

    @classmethod
    def exists(cls, index_dir: Path | None = None) -> bool:
        index_dir = Path(index_dir or config.INDEX_DIR)
        return (index_dir / VECTORS_FILE).exists() and (index_dir / META_FILE).exists()

    # --- search --------------------------------------------------------------

    def search(
        self,
        query_vector: np.ndarray,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        source_filter: str | None = None,
    ) -> list[SearchHit]:
        """Return the top_k most similar chunks, best first.

        Vectors are L2-normalised at embed time, so the dot product is cosine
        similarity in [-1, 1].
        """
        top_k = top_k or config.TOP_K
        min_score = config.MIN_SCORE if min_score is None else min_score

        if len(self.vectors) == 0:
            return []

        scores = self.vectors @ query_vector.astype(np.float32)

        # Restrict the candidate pool before ranking, so a filtered search still
        # returns top_k results rather than whatever survives from a global top_k.
        candidates = np.arange(len(scores))
        if source_filter:
            needle = source_filter.lower()
            candidates = np.array(
                [i for i in candidates if needle in self.chunks[i]["source"].lower()],
                dtype=int,
            )
            if candidates.size == 0:
                return []

        pool_scores = scores[candidates]
        k = min(top_k, candidates.size)
        # argpartition gets the top-k cheaply; sort only that slice.
        top_local = np.argpartition(-pool_scores, k - 1)[:k]
        top_local = top_local[np.argsort(-pool_scores[top_local])]

        hits = []
        for local_idx in top_local:
            score = float(pool_scores[local_idx])
            if score < min_score:
                continue
            chunk = self.chunks[int(candidates[local_idx])]
            hits.append(
                SearchHit(
                    score=score,
                    text=chunk["text"],
                    source=chunk["source"],
                    ordinal=chunk["ordinal"],
                    id=chunk["id"],
                )
            )
        return hits

    # --- introspection -------------------------------------------------------

    def sources(self) -> dict[str, int]:
        """Map of source document -> number of chunks."""
        counts: dict[str, int] = {}
        for chunk in self.chunks:
            counts[chunk["source"]] = counts.get(chunk["source"], 0) + 1
        return dict(sorted(counts.items()))

    def __len__(self) -> int:
        return len(self.chunks)
