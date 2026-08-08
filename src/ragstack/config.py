"""Configuration: paths, model IDs, and tunables.

Everything is overridable by environment variable so the MCP server, the CLI, and
tests can point at different corpora without code changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _project_root() -> Path:
    """Repo root — the directory containing pyproject.toml."""
    return Path(__file__).resolve().parents[2]


ROOT = Path(os.environ.get("RAGSTACK_ROOT", _project_root()))

# Where source documents live. Drop .md / .txt / .pdf files in here.
DOCS_DIR = Path(os.environ.get("RAGSTACK_DOCS_DIR", ROOT / "docs"))

# Where the built index is persisted.
INDEX_DIR = Path(os.environ.get("RAGSTACK_INDEX_DIR", ROOT / ".ragstack_index"))

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".pdf"}

# --- Embeddings (local, no API key) ------------------------------------------
# all-MiniLM-L6-v2: 384-dim, ~90MB, fast on CPU. Downloads once to the HF cache.
EMBED_MODEL = os.environ.get("RAGSTACK_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_BATCH_SIZE = int(os.environ.get("RAGSTACK_EMBED_BATCH", "32"))

# --- Chunking ----------------------------------------------------------------
CHUNK_SIZE = int(os.environ.get("RAGSTACK_CHUNK_SIZE", "1200"))  # characters
CHUNK_OVERLAP = int(os.environ.get("RAGSTACK_CHUNK_OVERLAP", "200"))

# --- Retrieval ---------------------------------------------------------------
TOP_K = int(os.environ.get("RAGSTACK_TOP_K", "5"))
# Cosine scores below this are treated as "no relevant context found".
MIN_SCORE = float(os.environ.get("RAGSTACK_MIN_SCORE", "0.15"))

# --- Generation --------------------------------------------------------------
# Who answers `ragstack ask` / the rag_answer tool:
#   anthropic  Claude over the API. Needs a credential. Default.
#   ollama     A local model. No key, no network past localhost.
LLM_BACKEND = os.environ.get("RAGSTACK_LLM_BACKEND", "anthropic").strip().lower()

# Opus 5 thinks by default, and max_tokens caps thinking + visible text together,
# so leave real headroom here.
ANSWER_MODEL = os.environ.get("RAGSTACK_ANSWER_MODEL", "claude-opus-5")
ANSWER_MAX_TOKENS = int(os.environ.get("RAGSTACK_ANSWER_MAX_TOKENS", "8000"))
ANSWER_EFFORT = os.environ.get("RAGSTACK_ANSWER_EFFORT", "medium")  # low|medium|high|xhigh|max

# --- Local generation (Ollama) -----------------------------------------------
OLLAMA_HOST = os.environ.get("RAGSTACK_OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("RAGSTACK_OLLAMA_MODEL", "llama3.2:3b")

# The KV cache is allocated for the entire window at load time, so this is a
# RAM setting as much as a length one: llama3.2's full 131072-token window wants
# ~14GB. 4096 holds a 5-passage prompt comfortably on an 8GB machine.
OLLAMA_NUM_CTX = int(os.environ.get("RAGSTACK_OLLAMA_NUM_CTX", "4096"))

# Answer ceiling, in tokens. Shares OLLAMA_NUM_CTX with the prompt.
OLLAMA_MAX_TOKENS = int(os.environ.get("RAGSTACK_OLLAMA_MAX_TOKENS", "1024"))

# Generous, because CPU-only inference is measured in minutes, not seconds.
OLLAMA_TIMEOUT = float(os.environ.get("RAGSTACK_OLLAMA_TIMEOUT", "600"))
OLLAMA_TEMPERATURE = float(os.environ.get("RAGSTACK_OLLAMA_TEMPERATURE", "0.2"))

BACKENDS = ("anthropic", "ollama")


def model_for(backend: str | None = None) -> str:
    """The model id the given backend will actually use."""
    backend = (backend or LLM_BACKEND).strip().lower()
    return OLLAMA_MODEL if backend == "ollama" else ANSWER_MODEL
