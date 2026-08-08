"""Document loading and chunking.

Chunks are split on paragraph boundaries where possible so a chunk rarely cuts a
sentence in half, then packed up to CHUNK_SIZE characters with CHUNK_OVERLAP
characters of tail carried into the next chunk for continuity.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config


@dataclass
class Chunk:
    """One retrievable unit of text plus where it came from."""

    id: str
    text: str
    source: str  # path relative to DOCS_DIR
    ordinal: int  # position of this chunk within its source document
    meta: dict = field(default_factory=dict)


def read_document(path: Path) -> str:
    """Extract plain text from a supported file. Returns '' if nothing readable."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:  # pragma: no cover - pypdf is a declared dependency
            raise RuntimeError("pypdf is required to index PDF files") from None
        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)

    return path.read_text(encoding="utf-8", errors="replace")


def discover(docs_dir: Path | None = None) -> list[Path]:
    """All indexable files under docs_dir, sorted for a stable index."""
    docs_dir = docs_dir or config.DOCS_DIR
    if not docs_dir.exists():
        return []
    return sorted(
        p
        for p in docs_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in config.SUPPORTED_SUFFIXES
    )


def _split_paragraphs(text: str) -> list[str]:
    # Normalise newlines, then split on blank lines.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _hard_split(paragraph: str, size: int) -> list[str]:
    """Break a single oversized paragraph into size-bounded pieces."""
    return [paragraph[i : i + size] for i in range(0, len(paragraph), size)]


def chunk_text(
    text: str,
    *,
    size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Split text into overlapping, paragraph-aligned chunks."""
    size = size or config.CHUNK_SIZE
    overlap = overlap if overlap is not None else config.CHUNK_OVERLAP
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    # A paragraph longer than `size` can never be packed, so pre-split those.
    paragraphs: list[str] = []
    for para in _split_paragraphs(text):
        paragraphs.extend(_hard_split(para, size) if len(para) > size else [para])

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= size:
            current = candidate
            continue

        # Candidate would overflow — emit what we have and start fresh, carrying
        # the tail of the emitted chunk forward as overlap.
        if current:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{para}".strip() if tail else para
        else:
            current = para

    if current:
        chunks.append(current)

    return chunks


def chunk_document(path: Path, docs_dir: Path | None = None) -> list[Chunk]:
    """Load one file and return its chunks with stable, content-derived IDs."""
    docs_dir = docs_dir or config.DOCS_DIR
    raw = read_document(path)
    if not raw.strip():
        return []

    try:
        source = str(path.relative_to(docs_dir))
    except ValueError:
        source = str(path)
    source = source.replace("\\", "/")

    chunks = []
    for ordinal, text in enumerate(chunk_text(raw)):
        digest = hashlib.sha256(f"{source}:{ordinal}:{text}".encode()).hexdigest()[:16]
        chunks.append(
            Chunk(
                id=digest,
                text=text,
                source=source,
                ordinal=ordinal,
                meta={"chars": len(text)},
            )
        )
    return chunks


def chunk_corpus(docs_dir: Path | None = None) -> list[Chunk]:
    """Load and chunk every supported document under docs_dir."""
    docs_dir = docs_dir or config.DOCS_DIR
    out: list[Chunk] = []
    for path in discover(docs_dir):
        out.extend(chunk_document(path, docs_dir))
    return out
