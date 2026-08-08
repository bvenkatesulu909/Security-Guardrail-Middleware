"""Errors this package raises deliberately.

They live here rather than in `llm` so a backend can raise them without
importing `llm`, which imports the backends.
"""

from __future__ import annotations


class RagStackError(RuntimeError):
    """Base class for errors this package raises deliberately."""


class MissingCredentialsError(RagStackError):
    """No usable Anthropic credential was found."""


class InvalidCredentialsError(RagStackError):
    """A credential was supplied and the API rejected it.

    Kept separate from `MissingCredentialsError` because the fix is different:
    one means "set a key", the other means "the key you set is wrong".
    """


class ModelRefusalError(RagStackError):
    """The model's safety classifiers declined the request."""


class LocalModelError(RagStackError):
    """The local model server was unreachable, or refused the request."""
