"""A registry that records (and can interrupt) provider calls, for observing what a run generated.

Wraps the real built-in providers, so a run behaves exactly as usual; it only notes which provider
methods were called with which requests, and can raise ``KeyboardInterrupt`` (a stand-in for a
killed process) when a call matches ``crash_when``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from vidpipe.contracts import Provider, ProviderKind
from vidpipe.registry import Registry, default_registry

METHODS: dict[ProviderKind, str] = {
    ProviderKind.TEXT: "complete",
    ProviderKind.TRANSLATION: "translate",
    ProviderKind.TTS: "synthesize",
    ProviderKind.KEYFRAMER: "generate",
    ProviderKind.IMAGE_TO_VIDEO: "animate",
    ProviderKind.MUSIC: "compose",
    ProviderKind.SONG: "sing",
}


@dataclass
class Call:
    kind: ProviderKind
    request: Any

    @property
    def output_stem(self) -> str:
        """``shot_02`` for a request writing ``.../shot_02.<ext>``."""
        return self.request.output_path.stem


@dataclass
class Recorder:
    calls: list[Call] = field(default_factory=list[Call])
    crash_when: Callable[[Call], bool] | None = None

    def of(self, kind: ProviderKind) -> list[Call]:
        return [c for c in self.calls if c.kind == kind]

    def stems(self, kind: ProviderKind, language: str | None = None) -> list[str]:
        return sorted(
            f"{c.request.language}/{c.output_stem}" if language is None else c.output_stem
            for c in self.of(kind)
            if language is None or c.request.language == language
        )


class RecordingRegistry(Registry):
    def __init__(self, recorder: Recorder, base: Registry | None = None) -> None:
        super().__init__()
        self.recorder = recorder
        self.base = base or default_registry()

    def create(self, kind: ProviderKind, name: str, **options: Any) -> Provider[Any]:
        provider = self.base.create(kind, name, **options)
        method = METHODS[kind]
        real = getattr(provider, method)

        def wrapper(request: BaseModel) -> Any:
            call = Call(kind, request)
            if self.recorder.crash_when is not None and self.recorder.crash_when(call):
                raise KeyboardInterrupt
            self.recorder.calls.append(call)
            return real(request)

        setattr(provider, method, wrapper)
        return provider
