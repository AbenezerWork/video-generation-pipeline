"""Build the provider a stage will use from its ``vidpipe.yaml`` selection, including fallback
chains (``script: [gemini-cli, claude-cli]``).

Text providers act on a fallback chain, and so does translation when text providers do it
(``translation: [gemini-cli, claude-cli]``: wrapped in :class:`~vidpipe.translate.TextTranslator`;
a registered translation provider such as ``fake-translation`` is used as is). For other stages
``fallback:`` is declared and validated but ignored (``narration: {name: edge-tts, fallback:
[mms-tts]}``).
"""

from __future__ import annotations

from typing import Any

from vidpipe.config import ProviderSelection
from vidpipe.contracts import Provider, ProviderKind, TextProvider
from vidpipe.registry import Registry, UnknownProvider, default_registry
from vidpipe.text import FallbackTextProvider
from vidpipe.translate import TextTranslator


def build_provider(
    registry: Registry, kind: ProviderKind, selection: ProviderSelection
) -> Provider[Any]:
    """Create the selected provider; for text stages with fallbacks, a chain of them in order."""
    if kind is ProviderKind.TRANSLATION:
        try:
            return registry.create(kind, selection.name, **selection.options)
        except UnknownProvider:
            return _build_text_translator(registry, selection)  # a chain of text providers
    primary = registry.create(kind, selection.name, **selection.options)
    if kind is not ProviderKind.TEXT or not selection.fallback:
        return primary
    chain = [primary] + [registry.create(kind, f.name, **f.options) for f in selection.fallback]
    return FallbackTextProvider([p for p in chain if isinstance(p, TextProvider)])


def _build_text_translator(registry: Registry, selection: ProviderSelection) -> TextTranslator:
    texts: list[TextProvider] = []
    for member in (selection, *selection.fallback):
        try:
            provider = registry.create(ProviderKind.TEXT, member.name, **member.options)
        except UnknownProvider:
            known = ", ".join(
                [*registry.names(ProviderKind.TRANSLATION), *registry.names(ProviderKind.TEXT)]
            )
            raise UnknownProvider(
                f"no translation or text provider named {member.name!r} (registered: {known})"
            ) from None
        if isinstance(provider, TextProvider):
            texts.append(provider)
    return TextTranslator(texts)


def describe(
    kind: ProviderKind, selection: ProviderSelection, registry: Registry | None = None
) -> str:
    """The provider label shown by ``plan`` and recorded in the manifest (``a > b`` for a chain)."""
    if kind is ProviderKind.TEXT:
        return selection.label
    if kind is ProviderKind.TRANSLATION:
        # Text providers do the translation unless the name is a registered translation provider.
        known = (registry or default_registry()).names(kind)
        return selection.name if selection.name in known else selection.label
    return selection.name
