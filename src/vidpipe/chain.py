"""Build the provider a stage will use from its ``vidpipe.yaml`` selection, including fallback
chains (``script: [gemini-cli, claude-cli]``).

Only text providers act on a fallback chain today. For other stages ``fallback:`` is declared and
validated but ignored (``narration: {name: edge-tts, fallback: [mms-tts]}``); translation joins
text in ticket 07 by adding its chain wrapper to :func:`build_provider` and :func:`describe`.
"""

from __future__ import annotations

from typing import Any

from vidpipe.config import ProviderSelection
from vidpipe.contracts import Provider, ProviderKind, TextProvider
from vidpipe.registry import Registry
from vidpipe.text import FallbackTextProvider


def build_provider(
    registry: Registry, kind: ProviderKind, selection: ProviderSelection
) -> Provider[Any]:
    """Create the selected provider; for text stages with fallbacks, a chain of them in order."""
    primary = registry.create(kind, selection.name, **selection.options)
    if kind is not ProviderKind.TEXT or not selection.fallback:
        return primary
    chain = [primary] + [registry.create(kind, f.name, **f.options) for f in selection.fallback]
    return FallbackTextProvider([p for p in chain if isinstance(p, TextProvider)])


def describe(kind: ProviderKind, selection: ProviderSelection) -> str:
    """The provider label shown by ``plan`` and recorded in the manifest (``a > b`` for a chain)."""
    return selection.label if kind is ProviderKind.TEXT else selection.name
