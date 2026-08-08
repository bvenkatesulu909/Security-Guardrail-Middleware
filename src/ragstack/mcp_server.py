"""MCP server exposing the RAG index as tools.

Run over stdio (what Claude Desktop / Claude Code launch):
    uv run ragstack serve

The retrieval tools need no model at all. Only `rag_answer` calls one — Claude
or a local model, per RAGSTACK_LLM_BACKEND — and it is the odd one out by
design: an MCP client is usually already an LLM, so `rag_search` is the primary
tool, handing passages back and letting the calling model do the reasoning.
"""

from __future__ import annotations

import functools
import os
import sys
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Callable

# Quiet the model-loading chatter before anything can import transformers.
# See `_no_stdout` below for why stray stdout writes are fatal here.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TQDM_DISABLE", "1")

from mcp.server.fastmcp import FastMCP  # noqa: E402

from . import __version__, config, index, llm, retrieve  # noqa: E402
from .store import VectorStore  # noqa: E402


@contextmanager
def _no_stdout():
    """Send anything written to stdout to stderr instead.

    The stdio transport writes JSON-RPC frames to `sys.stdout.buffer` and holds
    its own wrapper around it. A stray `print()` or progress bar from any
    dependency lands mid-frame, the client fails to parse the line, and the
    session wedges with no error on either side. Reassigning `sys.stdout` is
    safe precisely because the transport kept its own reference to the buffer.
    """
    original = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = original


# Cleared while the background warmup holds the stdout redirect, so a tool call
# can never restore the real stdout out from under it. Set by default, so
# importing this module and calling a tool directly still works.
_warm_done = threading.Event()
_warm_done.set()
_warm_requested = False


def _protocol_safe(fn: Callable) -> Callable:
    """Wrap a tool so its output can never corrupt the protocol stream."""

    @functools.wraps(fn)  # keeps the signature FastMCP derives its schema from
    def wrapper(*args, **kwargs):
        _warm_done.wait()  # only ever waits during the startup load
        with _no_stdout():
            return fn(*args, **kwargs)

    return wrapper


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    """Start the model warmup, on the one hook with the right timing.

    Two deadlines box this in. Loading the model inline before `mcp.run` takes
    ~30s and blows the handshake budget a client allows (Claude Code gives it
    30s), so it has to happen off-thread. But `stdio_server` wraps whatever
    `sys.stdout` points at when it opens, so a thread that starts any earlier
    can win the race and redirect stdout first — and then every JSON-RPC frame
    goes to stderr and the client sees a dead server.

    The lifespan runs after the transport has wrapped the real stdout and
    before the first request, which is the window where neither is true.
    """
    if _warm_requested and VectorStore.exists():
        _warm_done.clear()
        threading.Thread(target=_warm_model, name="ragstack-warmup", daemon=True).start()
    yield {}


mcp = FastMCP(
    "ragstack",
    instructions=(
        "Semantic search over a local document corpus. Call `rag_search` to "
        "retrieve passages relevant to a question and cite them by their "
        "`source` field. Call `rag_index_status` first if you need to know what "
        "is actually indexed before answering."
    ),
    log_level="WARNING",  # per-request INFO lines are noise on a stdio server
    lifespan=_lifespan,
)

# FastMCP has no `version` argument, so it advertises the MCP SDK's version.
# Report ours instead, so clients see the server they're actually talking to.
mcp._mcp_server.version = __version__


def _require_index() -> VectorStore | None:
    """Return the store, or None if no index has been built yet."""
    if not VectorStore.exists():
        return None
    return retrieve.get_store()


@mcp.tool()
@_protocol_safe
def rag_search(
    query: str,
    top_k: int = config.TOP_K,
    source_filter: str | None = None,
    min_score: float | None = None,
) -> dict[str, Any]:
    """Search the indexed documents for passages relevant to a query.

    Args:
        query: What to search for. Natural language works better than keywords.
        top_k: How many passages to return (default 5).
        source_filter: Only match documents whose path contains this substring.
        min_score: Cosine similarity floor, 0-1. Lower it to widen a thin result set.

    Returns the matching passages with their source paths and similarity scores.
    """
    if _require_index() is None:
        return {
            "error": "no_index",
            "message": (
                f"No index found at {config.INDEX_DIR}. Build one by running "
                f"`ragstack index` after putting documents in {config.DOCS_DIR}."
            ),
        }

    try:
        hits = retrieve.search(
            query,
            top_k=top_k,
            min_score=min_score,
            source_filter=source_filter,
        )
    except ValueError as exc:
        return {"error": "bad_request", "message": str(exc)}

    return {
        "query": query,
        "count": len(hits),
        "results": [
            {
                "rank": i,
                "score": round(hit.score, 4),
                "source": hit.citation(),
                "text": hit.text,
            }
            for i, hit in enumerate(hits, start=1)
        ],
    }


@mcp.tool()
@_protocol_safe
def rag_index_status() -> dict[str, Any]:
    """Report what is currently indexed: document count, chunk count, and the
    per-document chunk breakdown. Use this to check coverage before answering."""
    store = _require_index()
    if store is None:
        return {
            "indexed": False,
            "docs_dir": str(config.DOCS_DIR),
            "index_dir": str(config.INDEX_DIR),
            "message": "No index built yet. Run `ragstack index`.",
        }

    return {
        "indexed": True,
        "chunks": len(store),
        "documents": len(store.sources()),
        "sources": store.sources(),
        "info": store.info,
    }


@mcp.tool()
@_protocol_safe
def rag_answer(
    question: str,
    top_k: int = config.TOP_K,
    source_filter: str | None = None,
) -> dict[str, Any]:
    """Answer a question with a second model, grounded strictly in the indexed
    documents.

    Prefer `rag_search` when you can reason over the passages yourself — this
    tool spends a separate model call. Which model depends on the server's
    RAGSTACK_LLM_BACKEND: Claude over the API (needs a key), or a local model
    served by Ollama (no key, but slower).

    Args:
        question: The question to answer from the corpus.
        top_k: How many passages to ground the answer in.
        source_filter: Restrict retrieval to documents whose path contains this.
    """
    if _require_index() is None:
        return {
            "error": "no_index",
            "message": f"No index found at {config.INDEX_DIR}. Run `ragstack index`.",
        }

    try:
        result = llm.answer(question, top_k=top_k, source_filter=source_filter)
    except llm.MissingCredentialsError as exc:
        return {"error": "no_credentials", "message": str(exc)}
    except llm.InvalidCredentialsError as exc:
        return {"error": "invalid_credentials", "message": str(exc)}
    except llm.ModelRefusalError as exc:
        return {"error": "refusal", "message": str(exc)}
    except llm.LocalModelError as exc:
        return {"error": "local_model", "message": str(exc)}
    except ValueError as exc:
        return {"error": "bad_request", "message": str(exc)}

    return {
        "answer": result.answer,
        "citations": result.citations,
        "backend": config.LLM_BACKEND,
        "model": result.model,
        "stop_reason": result.stop_reason,
        "usage": result.usage,
    }


@mcp.tool()
@_protocol_safe
def rag_reindex() -> dict[str, Any]:
    """Rebuild the index from the documents on disk. Run this after adding,
    editing, or removing files in the documents directory."""
    try:
        store = index.build_index(show_progress=False, verbose=False)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": "index_failed", "message": str(exc)}

    retrieve.get_store(reload=True)
    return {
        "indexed": True,
        "chunks": len(store),
        "documents": len(store.sources()),
        "message": f"Rebuilt index at {config.INDEX_DIR}",
    }


@mcp.resource("rag://sources")
@_protocol_safe
def list_sources() -> str:
    """The list of documents currently in the index."""
    store = _require_index()
    if store is None:
        return f"No index built. Run `ragstack index` after adding files to {config.DOCS_DIR}."

    lines = [f"{len(store.sources())} document(s), {len(store)} chunk(s):", ""]
    lines += [f"  {source}  ({count} chunks)" for source, count in store.sources().items()]
    return "\n".join(lines)


def _warm_model() -> None:
    """Load the weights so the first `rag_search` answers in milliseconds
    instead of stalling.

    Only the weights — `main` has already imported the library on the main
    thread, which is the part that cannot happen here. See `main`.
    """
    try:
        with _no_stdout():
            from . import embed

            embed.embed_one("warmup")
        print("ragstack: embedding model ready", file=sys.stderr)
    except Exception as exc:  # never let warmup take the server down
        print(f"ragstack: warmup skipped ({exc})", file=sys.stderr)
    finally:
        _warm_done.set()


def main(*, warm: bool = True) -> None:
    """Entry point — serves over stdio.

    The embedding model is loaded alongside the handshake rather than before it,
    so the first `rag_search` answers in milliseconds without the startup itself
    outrunning the client's connect timeout. See `_lifespan`, which owns the
    timing; this only says whether to warm at all.

    The *import* is the exception, and it happens here: on the main thread,
    before any other thread exists. Importing sentence-transformers off the main
    thread deadlocks inside scipy's BLAS extension loader, and the server wedges
    with no error on either side — it makes no difference whether the import
    lands in the warmup thread or in the worker FastMCP hands a tool call to,
    because whichever gets there first is the one that hangs. Loading the
    weights off-thread afterwards is fine; only the import has to be serialised.
    It costs ~16s, which still fits the 30s a client allows for the handshake.
    """
    import sentence_transformers  # noqa: F401

    global _warm_requested
    _warm_requested = warm

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
