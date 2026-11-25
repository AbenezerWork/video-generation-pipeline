"""Build the provider a stage will use from its ``vidpipe.yaml`` selection, including fallback
chains (``script: [gemini-cli, claude-cli]``).

Only text providers support chains today; translation joins them in ticket 07 by adding its
wrapper to :func:`build_provider`.
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
    """Create the selected provider; with fallbacks, a chain that tries them in order."""
    primary = registry.create(kind, selection.name, **selection.options)
    if not selection.fallbacks:
        return primary
    if kind is not ProviderKind.TEXT:
        raise ValueError(f"fallback chains are only supported for text providers, not {kind.value}")
    chain = [primary] + [registry.create(kind, f.name, **f.options) for f in selection.fallbacks]
    return FallbackTextProvider([p for p in chain if isinstance(p, TextProvider)])
