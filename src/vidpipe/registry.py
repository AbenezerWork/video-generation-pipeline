"""Provider registry: built-in providers plus third-party ones via entry points.

To add a provider: subclass the contract class for its kind (``vidpipe.contracts``), set ``name``
and ``capabilities``, decorate with ``@register`` (or expose the class through a
``vidpipe.providers`` entry point), and select it by name in ``vidpipe.yaml``.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any, TypeVar

from vidpipe.contracts import Provider, ProviderKind

P = TypeVar("P", bound=type[Provider])

ENTRY_POINT_GROUP = "vidpipe.providers"


class UnknownProvider(KeyError):
    def __str__(self) -> str:
        return str(self.args[0])


class Registry:
    def __init__(self) -> None:
        self._providers: dict[tuple[ProviderKind, str], type[Provider]] = {}

    def register(self, cls: type[Provider]) -> None:
        key = (cls.kind, cls.name)
        if key in self._providers and self._providers[key] is not cls:
            raise ValueError(f"duplicate provider {cls.name!r} for kind {cls.kind.value!r}")
        self._providers[key] = cls

    def names(self, kind: ProviderKind) -> list[str]:
        return sorted(name for (k, name) in self._providers if k == kind)

    def classes(self, kind: ProviderKind | None = None) -> list[type[Provider]]:
        keys = sorted(self._providers, key=lambda key: (key[0].value, key[1]))
        return [self._providers[key] for key in keys if kind is None or key[0] == kind]

    def create(self, kind: ProviderKind, name: str, **options: Any) -> Provider:
        try:
            cls = self._providers[(kind, name)]
        except KeyError:
            known = ", ".join(self.names(kind)) or "none"
            raise UnknownProvider(
                f"no {kind.value} provider named {name!r} (registered: {known})"
            ) from None
        return cls(**options)

    def load_entry_points(self) -> None:
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            loaded = ep.load()
            if isinstance(loaded, type) and issubclass(loaded, Provider):
                self.register(loaded)


_BUILTIN_REGISTRY = Registry()
_loaded = False


def register(cls: P) -> P:
    """Class decorator registering a built-in provider."""
    _BUILTIN_REGISTRY.register(cls)
    return cls


def default_registry() -> Registry:
    """The registry with all built-in providers and any installed entry-point providers."""
    global _loaded
    if not _loaded:
        import vidpipe.providers  # noqa: F401  (importing registers the built-ins)

        _BUILTIN_REGISTRY.load_entry_points()
        _loaded = True
    return _BUILTIN_REGISTRY
