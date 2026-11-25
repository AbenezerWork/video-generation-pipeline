"""Text-provider plumbing shared by every text adapter and every stage that asks for text.

* :class:`TextProviderError` and its subclasses are what an adapter raises when it cannot answer.
  A fallback chain moves on to the next provider on any of them.
* :func:`extract_json` pulls the JSON object out of free-form model output.
* :func:`ask` is how a stage asks a provider for a validated Pydantic model: the model's JSON
  schema goes out with the request, and the model itself (plus an optional semantic ``check``)
  becomes the request's validator, so an adapter can re-prompt the CLI with the validation error.
* :class:`FallbackTextProvider` tries a configured chain of providers in order.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from vidpipe.contracts import (
    TextCapabilities,
    TextProvider,
    TextRequest,
    TextResponse,
    UnsupportedRequest,
)

M = TypeVar("M", bound=BaseModel)


class TextProviderError(Exception):
    """A text provider could not produce an answer."""


class ProviderUnavailable(TextProviderError):
    """The provider cannot run at all (executable missing, not installed, timed out)."""


class RateLimited(TextProviderError):
    """The provider (or its vendor) refused the call for rate, quota or capacity reasons."""


class InvalidOutput(TextProviderError):
    """The provider answered, but not with valid JSON that passes validation."""


class AllProvidersFailed(TextProviderError):
    """Every provider in a fallback chain failed."""


# ------------------------------------------------------------------------------ JSON extraction


def extract_json(text: str) -> dict[str, Any]:
    """Return the first JSON object found in ``text``.

    Handles bare JSON, JSON inside a Markdown code fence, and JSON surrounded by prose.
    Raises :class:`InvalidOutput` when no object can be decoded.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value  # pyright: ignore[reportUnknownVariableType]
        start = text.find("{", start + 1)
    raise InvalidOutput("the reply contains no JSON object")


# ---------------------------------------------------------------------------------- stage helper


def model_request(
    prompt: str, model: type[M], check: Callable[[M], None] | None = None
) -> TextRequest:
    """A text request whose answer must validate as ``model`` (and pass ``check``, if given)."""

    def validator(data: dict[str, Any]) -> None:
        parsed = model.model_validate(data)  # pydantic.ValidationError is a ValueError
        if check is not None:
            check(parsed)

    return TextRequest(prompt=prompt, json_schema=model.model_json_schema(), validator=validator)


def ask(
    provider: TextProvider,
    prompt: str,
    model: type[M],
    check: Callable[[M], None] | None = None,
) -> M:
    """Ask ``provider`` for a ``model``. Raises :class:`TextProviderError` if it cannot answer.

    ``check`` rejects answers that are well-formed but wrong (it should raise ``ValueError``);
    adapters re-prompt with its message. The answer is validated again here, so a provider that
    ignores the request's validator (a fake, say) still cannot hand a stage bad data.
    """
    request = model_request(prompt, model, check)
    response = provider.complete(request)
    try:
        parsed = model.model_validate(response.data)
        if check is not None:
            check(parsed)
    except ValueError as exc:
        raise InvalidOutput(f"{provider.name}: {exc}") from exc
    return parsed


# ---------------------------------------------------------------------------- fallback chain


class FallbackTextProvider(TextProvider):
    """Tries each provider of a chain in order, moving on after a failure or rate limit."""

    name: ClassVar[str] = "fallback"  # pyright: ignore[reportIncompatibleVariableOverride]

    def __init__(self, providers: list[TextProvider]) -> None:
        if not providers:
            raise ValueError("a fallback chain needs at least one provider")
        super().__init__()
        self.providers = providers
        self.capabilities = TextCapabilities(
            structured_output=all(p.capabilities.structured_output for p in providers)
        )
        #: ``(provider name, error)`` for every provider that failed, across all calls.
        self.failures: list[tuple[str, str]] = []
        #: Name of the provider that answered the most recent call.
        self.last_used: str | None = None

    def complete(self, request: TextRequest) -> TextResponse:
        errors: list[str] = []
        for provider in self.providers:
            try:
                response = provider.complete(request)
            except (TextProviderError, UnsupportedRequest) as exc:
                self.failures.append((provider.name, str(exc)))
                errors.append(f"{provider.name}: {exc}")
                continue
            self.last_used = provider.name
            return response
        raise AllProvidersFailed("; ".join(errors))
