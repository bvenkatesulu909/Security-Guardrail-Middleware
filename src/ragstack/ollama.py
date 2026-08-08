"""Generation with a local model served by Ollama.

The offline half of the LLM layer: no API key, nothing leaving the machine.
Speaks Ollama's HTTP API directly over `urllib`, so supporting it costs the
package no new dependency.

Two things about a RAM-bound host shape this module:

* The KV cache is allocated for the *whole* context window up front, so
  `num_ctx` is a memory setting, not just a length limit. Ask for more than
  the box has and the server fails the request outright — see
  `_allocation_help`.
* That capped window then has to hold the retrieved passages. `fit_hits`
  drops the weakest ones rather than letting the server silently truncate the
  prompt, which on Ollama trims from the front and would quietly eat the
  system prompt before anything else.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from . import config
from .errors import LocalModelError
from .store import SearchHit

# Rough characters-per-token for context budgeting. English prose runs ~4 on
# Llama tokenizers; the low estimate is deliberate, so the arithmetic errs
# toward dropping a passage rather than overflowing the window.
_CHARS_PER_TOKEN = 3.5

# Per-passage framing added by `retrieve.format_context`: the "[n] source: ...
# (similarity ...)" header plus the separator between blocks.
_PER_PASSAGE_CHARS = 90

# Slack left inside the window for the chat template's own scaffolding
# (role headers, BOS/EOS turns) which never appears in our prompt string.
_RESERVE_TOKENS = 128


def _endpoint(path: str) -> str:
    return f"{config.OLLAMA_HOST.rstrip('/')}{path}"


# --- error mapping -----------------------------------------------------------


def _unreachable_help(host: str, detail: str) -> str:
    return (
        f"Cannot reach Ollama at {host} ({detail}).\n"
        "Start the server, then retry:\n"
        "    ollama serve\n"
        "Point somewhere else with RAGSTACK_OLLAMA_HOST.\n\n"
        "Retrieval (`ragstack search`) needs no model and works regardless."
    )


def _allocation_help(model: str, num_ctx: int) -> str:
    return (
        f"Ollama could not allocate memory to run {model!r} with a "
        f"{num_ctx}-token context.\n"
        "The KV cache is sized for the whole window up front, so this is a RAM "
        "ceiling, not a bad install — reinstalling will not change it.\n"
        "Either lower RAGSTACK_OLLAMA_NUM_CTX (4096 is a safe floor for a "
        "5-passage prompt), or start the server itself with a capped context:\n"
        "    $env:OLLAMA_CONTEXT_LENGTH = '4096'; ollama serve\n"
        "The Ollama desktop app does not pass that variable through to the "
        "server, so a model launched by it loads at its full advertised window."
    )


def _missing_model_help(model: str) -> str:
    return (
        f"Ollama has no model named {model!r}.\n"
        f"Pull it once:  ollama pull {model}\n"
        "Or point RAGSTACK_OLLAMA_MODEL at one from `ollama list`."
    )


def _as_local_error(body: str, status: int, *, model: str, num_ctx: int) -> LocalModelError:
    """Turn an Ollama error payload into something worth reading.

    The server reports both "you asked for a model I don't have" and "I ran out
    of memory" as ordinary HTTP errors whose body is `{"error": "..."}`, and the
    memory failure in particular reads like a broken install if taken at face
    value.
    """
    detail = body.strip()
    try:
        detail = json.loads(body).get("error", detail)
    except (ValueError, AttributeError):
        pass

    lowered = detail.lower()
    if "not found" in lowered and "model" in lowered:
        return LocalModelError(_missing_model_help(model))
    if "kv cache" in lowered or "allocate" in lowered or "memory" in lowered:
        return LocalModelError(f"{_allocation_help(model, num_ctx)}\n\nServer said: {detail}")
    return LocalModelError(f"Ollama returned HTTP {status}: {detail}")


# --- context budgeting -------------------------------------------------------


def fit_hits(
    hits: list[SearchHit],
    *,
    overhead_chars: int,
    num_ctx: int | None = None,
    num_predict: int = 0,
) -> tuple[list[SearchHit], int]:
    """Trim `hits` (best first) to what will fit alongside the answer.

    Returns the kept hits and how many were dropped. The top hit is always
    kept — truncated if it alone overruns the budget — because answering from
    the best passage beats refusing to answer at all.
    """
    num_ctx = config.OLLAMA_NUM_CTX if num_ctx is None else num_ctx
    budget_tokens = num_ctx - num_predict - _RESERVE_TOKENS
    budget_chars = int(budget_tokens * _CHARS_PER_TOKEN) - overhead_chars

    if not hits:
        return [], 0

    if budget_chars <= 0:
        raise LocalModelError(
            f"No room left in a {num_ctx}-token context for any passage once the "
            f"question and a {num_predict}-token answer are accounted for. Raise "
            "RAGSTACK_OLLAMA_NUM_CTX or lower --max-tokens."
        )

    kept: list[SearchHit] = []
    used = 0
    for hit in hits:
        cost = len(hit.text) + _PER_PASSAGE_CHARS
        if kept and used + cost > budget_chars:
            break
        used += cost
        kept.append(hit)

    # A single oversized passage: keep it, but cut it to the budget so the
    # server does not trim the system prompt off the front instead.
    if len(kept) == 1 and used > budget_chars:
        room = max(budget_chars - _PER_PASSAGE_CHARS, 200)
        head = kept[0]
        kept = [
            SearchHit(
                score=head.score,
                text=head.text[:room] + "\n[passage truncated to fit the context window]",
                source=head.source,
                ordinal=head.ordinal,
                id=head.id,
            )
        ]

    return kept, len(hits) - len(kept)


# --- the call ----------------------------------------------------------------


def chat(
    prompt: str,
    *,
    system: str,
    model: str | None = None,
    num_ctx: int | None = None,
    num_predict: int | None = None,
    timeout: float | None = None,
    on_text: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Send one grounded turn to Ollama and collect the streamed reply.

    `on_text` receives content deltas as they arrive, for live CLI output.
    Streaming is not optional here: on a CPU-only host a full answer can take
    minutes, and a non-streaming request would spend that time looking hung.
    """
    model = model or config.OLLAMA_MODEL
    num_ctx = config.OLLAMA_NUM_CTX if num_ctx is None else num_ctx
    num_predict = config.OLLAMA_MAX_TOKENS if num_predict is None else num_predict
    timeout = config.OLLAMA_TIMEOUT if timeout is None else timeout

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            # Grounded extraction, not brainstorming: keep it close to the text.
            "temperature": float(config.OLLAMA_TEMPERATURE),
        },
    }

    request = urllib.request.Request(
        _endpoint("/api/chat"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    parts: list[str] = []
    final: dict[str, Any] = {}

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for line in response:
                frame = line.strip()
                if not frame:
                    continue
                try:
                    event = json.loads(frame)
                except ValueError:
                    continue  # keepalive or partial line; the next one resyncs

                # Failures can also arrive mid-stream, after a 200.
                if "error" in event:
                    raise _as_local_error(
                        json.dumps(event), 200, model=model, num_ctx=num_ctx
                    )

                delta = (event.get("message") or {}).get("content", "")
                if delta:
                    parts.append(delta)
                    if on_text is not None:
                        on_text(delta)

                if event.get("done"):
                    final = event
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise _as_local_error(body, exc.code, model=model, num_ctx=num_ctx) from exc
    except urllib.error.URLError as exc:
        raise LocalModelError(_unreachable_help(config.OLLAMA_HOST, str(exc.reason))) from exc
    except TimeoutError as exc:
        raise LocalModelError(
            f"Ollama did not respond within {timeout:.0f}s. A CPU-only host is slow — "
            "raise RAGSTACK_OLLAMA_TIMEOUT, lower --max-tokens, or retrieve fewer "
            "passages with -k."
        ) from exc

    return {
        "text": "".join(parts),
        "model": final.get("model", model),
        "done_reason": final.get("done_reason", "stop"),
        "usage": {
            "input_tokens": final.get("prompt_eval_count"),
            "output_tokens": final.get("eval_count"),
        },
    }


def probe(timeout: float = 2.0) -> dict[str, Any]:
    """Cheap liveness check for `ragstack status`. Never raises."""
    try:
        with urllib.request.urlopen(_endpoint("/api/version"), timeout=timeout) as response:
            version = json.loads(response.read().decode("utf-8")).get("version")
        return {"reachable": True, "version": version}
    except Exception as exc:  # noqa: BLE001 - status output, not a control path
        return {"reachable": False, "detail": str(getattr(exc, "reason", exc))}
