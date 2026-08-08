"""Answer synthesis, grounded in retrieved passages.

Two backends, selected by `RAGSTACK_LLM_BACKEND`:

    anthropic   Claude answers over the API. Needs a credential. Default.
    ollama      A local model answers. No key, nothing leaves the machine.

Both return the same `AnswerResult`, so the CLI and the MCP server never have
to know which one ran. Retrieval, the empty-result short-circuit, and the
prompt are shared — only the call itself differs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import anthropic

from . import config, ollama, retrieve
from .errors import (  # re-exported: callers catch these off `llm`
    InvalidCredentialsError,
    LocalModelError,
    MissingCredentialsError,
    ModelRefusalError,
    RagStackError,
)
from .store import SearchHit

__all__ = [
    "SYSTEM_PROMPT",
    "AnswerResult",
    "InvalidCredentialsError",
    "LocalModelError",
    "MissingCredentialsError",
    "ModelRefusalError",
    "RagStackError",
    "answer",
    "build_client",
    "build_prompt",
]

SYSTEM_PROMPT = """\
You answer questions using only the retrieved passages supplied in the user turn.

Rules:
- Ground every factual claim in the passages. Cite the passage number inline like [1] or [2][3].
- If the passages do not contain the answer, say so plainly and state what is missing. \
Do not fall back on general knowledge to fill the gap, and do not speculate.
- If the passages disagree, surface the disagreement rather than silently picking one.
- Answer at the length the question deserves. No preamble, no restating the question.
"""

# What `build_prompt` wraps around the passages and the question, in characters.
# Only used to budget a local model's context window.
_SCAFFOLD_CHARS = 80


@dataclass
class AnswerResult:
    """A grounded answer plus everything needed to audit it."""

    answer: str
    hits: list[SearchHit]
    model: str
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)

    @property
    def citations(self) -> list[str]:
        return [h.citation() for h in self.hits]


_CREDENTIAL_HELP = (
    "No Anthropic credential found. Either set an API key:\n"
    "    $env:ANTHROPIC_API_KEY = 'sk-ant-...'      # PowerShell, this session\n"
    "    setx ANTHROPIC_API_KEY 'sk-ant-...'        # PowerShell, persisted\n"
    "or add it to the .env file in the project root, or run `ant auth login`.\n"
    "Get a key at https://console.anthropic.com/settings/keys\n\n"
    "No key at hand? Answer locally instead — set RAGSTACK_LLM_BACKEND=ollama, "
    "or pass `--backend ollama`.\n"
    "Retrieval (`ragstack search`) works without any credential."
)

_REJECTED_HELP = (
    "The Anthropic API rejected the credential that is set — it is present but "
    "not valid.\n"
    "Common causes: the key was revoked or rotated, it was copied with a missing "
    "character or a trailing newline, or it belongs to a different organisation.\n"
    "Check which one is actually in play:\n"
    "    $env:ANTHROPIC_API_KEY.Length                # PowerShell, current session\n"
    "and compare against a fresh key from "
    "https://console.anthropic.com/settings/keys\n\n"
    "Note a real environment variable overrides the .env file, so a stale one in "
    "your shell wins over a corrected .env.\n"
    "Meanwhile, `--backend ollama` answers locally and `ragstack search` needs no "
    "credential at all."
)


def build_client() -> anthropic.Anthropic:
    """Construct the SDK client, letting it resolve credentials from the
    environment or an `ant auth login` profile.

    Note this succeeds even with no credential anywhere — the SDK only resolves
    auth when a request is built. See `_as_credentials_error`.
    """
    return anthropic.Anthropic()


def _as_credentials_error(
    exc: BaseException,
) -> MissingCredentialsError | InvalidCredentialsError | None:
    """Recognise a credential problem however the SDK reports it, and say which.

    The two arrive by different routes. With no key set anywhere, the client
    constructs cleanly and the SDK raises a plain `TypeError` while building
    request headers. A key that was supplied and rejected comes back as
    `AuthenticationError` from the API instead. Telling someone who just pasted
    a key that no key was found sends them to fix the wrong thing, so the two
    map to different errors.

    Matching the TypeError on its message keeps a genuine TypeError in our own
    request kwargs visible rather than disguised as an auth problem.
    """
    if isinstance(exc, anthropic.AuthenticationError):
        return InvalidCredentialsError(_REJECTED_HELP)
    if isinstance(exc, TypeError) and "resolve authentication method" in str(exc):
        return MissingCredentialsError(_CREDENTIAL_HELP)
    return None


def build_prompt(question: str, hits: list[SearchHit]) -> str:
    return (
        f"<retrieved_passages>\n{retrieve.format_context(hits)}\n</retrieved_passages>\n\n"
        f"Question: {question}"
    )


def answer(
    question: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    source_filter: str | None = None,
    index_dir: Path | None = None,
    backend: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
    on_text: Callable[[str], None] | None = None,
) -> AnswerResult:
    """Retrieve passages for `question`, then have the configured model answer
    from them.

    `on_text` receives text deltas as they stream, for live CLI output.
    """
    if not question or not question.strip():
        raise ValueError("question must not be empty")

    backend = (backend or config.LLM_BACKEND).strip().lower()
    if backend not in _BACKENDS:
        raise ValueError(
            f"unknown LLM backend {backend!r}. Set RAGSTACK_LLM_BACKEND (or pass "
            f"--backend) to one of: {', '.join(config.BACKENDS)}"
        )

    model = model or config.model_for(backend)
    hits = retrieve.search(
        question,
        top_k=top_k,
        min_score=min_score,
        source_filter=source_filter,
        index_dir=index_dir,
    )

    # Nothing cleared the relevance bar — don't spend a model call to be told so.
    if not hits:
        return AnswerResult(
            answer=(
                "No passages in the index cleared the relevance threshold for this "
                "question. Try rephrasing, lowering --min-score, or indexing more "
                "documents."
            ),
            hits=[],
            model=model,
            stop_reason="no_context",
        )

    return _BACKENDS[backend](
        question,
        hits,
        model=model,
        effort=effort,
        max_tokens=max_tokens,
        on_text=on_text,
    )


def _answer_anthropic(
    question: str,
    hits: list[SearchHit],
    *,
    model: str,
    effort: str | None,
    max_tokens: int | None,
    on_text: Callable[[str], None] | None,
) -> AnswerResult:
    client = build_client()
    request = {
        "model": model,
        "max_tokens": max_tokens or config.ANSWER_MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        # Opus 5 thinks by default; stated explicitly so the intent survives a
        # model swap. max_tokens covers thinking + visible text together.
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort or config.ANSWER_EFFORT},
        "messages": [{"role": "user", "content": build_prompt(question, hits)}],
    }

    try:
        # Streaming keeps long answers clear of HTTP timeouts and lets the CLI
        # render tokens as they arrive.
        with client.messages.stream(**request) as stream:
            if on_text is not None:
                for delta in stream.text_stream:
                    on_text(delta)
            message = stream.get_final_message()
    except (anthropic.AuthenticationError, TypeError) as exc:
        if (creds_error := _as_credentials_error(exc)) is not None:
            raise creds_error from exc
        raise

    # Check why generation stopped before trusting the content blocks.
    if message.stop_reason == "refusal":
        detail = getattr(message, "stop_details", None)
        category = getattr(detail, "category", None) or "unspecified"
        raise ModelRefusalError(
            f"The model declined this request (category: {category}). "
            "The retrieved passages or the question likely tripped a safety classifier."
        )

    text = "".join(block.text for block in message.content if block.type == "text")

    if message.stop_reason == "max_tokens":
        text += (
            "\n\n[truncated: hit the max_tokens ceiling — rerun with "
            "--max-tokens higher than the current limit]"
        )

    return AnswerResult(
        answer=text.strip(),
        hits=hits,
        model=message.model,
        stop_reason=message.stop_reason,
        usage={
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    )


def _answer_ollama(
    question: str,
    hits: list[SearchHit],
    *,
    model: str,
    effort: str | None,
    max_tokens: int | None,
    on_text: Callable[[str], None] | None,
) -> AnswerResult:
    # `effort` is an Anthropic control. Local models have no equivalent knob, so
    # it is accepted and ignored rather than made an error — the same command
    # should work against either backend.
    num_predict = max_tokens or config.OLLAMA_MAX_TOKENS

    # A local window is small enough that the passages have to be budgeted.
    # Report the kept hits, not the retrieved ones, so citations line up with
    # what the model was actually shown.
    kept, dropped = ollama.fit_hits(
        hits,
        overhead_chars=len(SYSTEM_PROMPT) + len(question) + _SCAFFOLD_CHARS,
        num_ctx=config.OLLAMA_NUM_CTX,
        num_predict=num_predict,
    )

    result = ollama.chat(
        build_prompt(question, kept),
        system=SYSTEM_PROMPT,
        model=model,
        num_ctx=config.OLLAMA_NUM_CTX,
        num_predict=num_predict,
        on_text=on_text,
    )

    text = result["text"].strip()
    done_reason = result["done_reason"]

    if done_reason == "length":
        text += (
            "\n\n[truncated: hit the max_tokens ceiling — rerun with "
            "--max-tokens higher than the current limit]"
        )
    if dropped:
        text += (
            f"\n\n[{dropped} lower-ranked passage(s) left out to fit the "
            f"{config.OLLAMA_NUM_CTX}-token context window]"
        )

    return AnswerResult(
        answer=text,
        hits=kept,
        model=result["model"],
        # Normalised to the Anthropic vocabulary so callers stay backend-agnostic.
        stop_reason={"stop": "end_turn", "length": "max_tokens"}.get(done_reason, done_reason),
        usage=result["usage"],
    )


_BACKENDS: dict[str, Callable[..., AnswerResult]] = {
    "anthropic": _answer_anthropic,
    "ollama": _answer_ollama,
}
