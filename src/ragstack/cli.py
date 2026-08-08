"""Command-line interface: index, search, ask, status, serve."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .store import VectorStore


def _print_err(message: str) -> None:
    print(message, file=sys.stderr)


# --- commands ----------------------------------------------------------------


def cmd_index(args: argparse.Namespace) -> int:
    from . import index

    docs_dir = Path(args.docs) if args.docs else config.DOCS_DIR
    try:
        store = index.build_index(docs_dir=docs_dir, show_progress=not args.quiet)
    except (FileNotFoundError, ValueError) as exc:
        _print_err(f"error: {exc}")
        return 1

    print(f"\n{len(store.sources())} document(s), {len(store)} chunk(s) indexed.")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from . import retrieve

    try:
        hits = retrieve.search(
            args.query,
            top_k=args.top_k,
            min_score=args.min_score,
            source_filter=args.source,
        )
    except FileNotFoundError as exc:
        _print_err(f"error: {exc}")
        return 1

    if not hits:
        print("No passages cleared the relevance threshold.")
        print(f"Try a different phrasing or lower --min-score (currently {config.MIN_SCORE}).")
        return 0

    for i, hit in enumerate(hits, start=1):
        print(f"\n[{i}] {hit.citation()}   similarity {hit.score:.3f}")
        print("-" * 72)
        snippet = hit.text if args.full else hit.text[:500]
        print(snippet)
        if not args.full and len(hit.text) > 500:
            print(f"... (+{len(hit.text) - 500} more chars; use --full)")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from . import llm

    question = " ".join(args.question)

    try:
        result = llm.answer(
            question,
            top_k=args.top_k,
            source_filter=args.source,
            backend=args.backend,
            effort=args.effort,
            max_tokens=args.max_tokens,
            on_text=None if args.quiet else lambda t: print(t, end="", flush=True),
        )
    except FileNotFoundError as exc:
        _print_err(f"error: {exc}")
        return 1
    except llm.MissingCredentialsError as exc:
        _print_err(f"\nerror: {exc}")
        return 2
    except llm.InvalidCredentialsError as exc:
        _print_err(f"\nerror: {exc}")
        return 5
    except llm.ModelRefusalError as exc:
        _print_err(f"\nerror: {exc}")
        return 3
    except llm.LocalModelError as exc:
        _print_err(f"\nerror: {exc}")
        return 4

    if args.quiet:
        print(result.answer)
    else:
        print()  # close out the streamed text

    if result.hits:
        print("\n" + "-" * 72)
        print("Sources:")
        for i, hit in enumerate(result.hits, start=1):
            print(f"  [{i}] {hit.citation()}   similarity {hit.score:.3f}")
    if result.usage:
        print(
            f"\n{result.model}  "
            f"in {result.usage.get('input_tokens')} / "
            f"out {result.usage.get('output_tokens')} tokens"
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    print(f"docs dir : {config.DOCS_DIR}")
    print(f"index dir: {config.INDEX_DIR}")
    print(f"embedder : {config.EMBED_MODEL}")
    print(f"backend  : {config.LLM_BACKEND}")
    print(f"answerer : {config.model_for()}")

    if config.LLM_BACKEND == "ollama":
        from . import ollama

        probe = ollama.probe()
        state = (
            f"up (ollama {probe['version']})"
            if probe["reachable"]
            else f"UNREACHABLE — {probe.get('detail')}"
        )
        print(f"           {config.OLLAMA_HOST} {state}")
        print(f"           context {config.OLLAMA_NUM_CTX}, answer cap {config.OLLAMA_MAX_TOKENS}")
    else:
        print(f"           effort {config.ANSWER_EFFORT}, max tokens {config.ANSWER_MAX_TOKENS}")

    if not VectorStore.exists():
        print("\nNo index built yet. Run:  ragstack index")
        return 0

    from . import retrieve

    store = retrieve.get_store()
    print(f"\nIndexed: {len(store.sources())} document(s), {len(store)} chunk(s)")
    built = store.info.get("built_at")
    if built:
        print(f"Built at: {built}")
    print()
    for source, count in store.sources().items():
        print(f"  {source}  ({count} chunks)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .mcp_server import main as serve_main

    # stdio is the MCP transport; anything on stdout that is not protocol
    # traffic corrupts the session, so status goes to stderr.
    _print_err("ragstack MCP server listening on stdio ...")
    serve_main()
    return 0


# --- parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ragstack",
        description="Local RAG over your documents, answered by Claude or a local model, "
        "exposed over MCP.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build the vector index from your documents")
    p_index.add_argument("--docs", help=f"document directory (default: {config.DOCS_DIR})")
    p_index.add_argument("-q", "--quiet", action="store_true", help="hide the progress bar")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", help="retrieve passages (no API key needed)")
    p_search.add_argument("query")
    p_search.add_argument("-k", "--top-k", type=int, default=config.TOP_K)
    p_search.add_argument("--source", help="only match documents whose path contains this")
    p_search.add_argument("--min-score", type=float, default=None)
    p_search.add_argument("--full", action="store_true", help="print whole passages")
    p_search.set_defaults(func=cmd_search)

    p_ask = sub.add_parser("ask", help="ask a model a question grounded in your documents")
    p_ask.add_argument("question", nargs="+")
    p_ask.add_argument("-k", "--top-k", type=int, default=config.TOP_K)
    p_ask.add_argument("--source", help="only match documents whose path contains this")
    p_ask.add_argument(
        "--backend",
        choices=list(config.BACKENDS),
        default=None,
        help=f"who answers (default: {config.LLM_BACKEND})",
    )
    p_ask.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        default=None,
        help=f"reasoning effort, anthropic backend only (default: {config.ANSWER_EFFORT})",
    )
    p_ask.add_argument("--max-tokens", type=int, default=None)
    p_ask.add_argument("-q", "--quiet", action="store_true", help="don't stream tokens")
    p_ask.set_defaults(func=cmd_ask)

    p_status = sub.add_parser("status", help="show configuration and index contents")
    p_status.set_defaults(func=cmd_status)

    p_serve = sub.add_parser("serve", help="run the MCP server over stdio")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _print_err("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
