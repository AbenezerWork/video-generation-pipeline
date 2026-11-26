"""Append a record for each generation attempt under the project's writer lock."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, cast

from vidpipe.contracts import Provider


@dataclass(frozen=True)
class CallSite:
    path: Path
    run_id: str
    stage: str
    artifact: str
    parameters: Mapping[str, Any]
    seed: int | None


@dataclass
class Attempt:
    gpu_seconds: float | None = None
    output_seconds: float = 0.0
    nested: bool = False


_PRIVATE_OPTION = re.compile(
    r"token|secret|pass(word|phrase)?|api.?key|credential|authorization|url", re.I
)


def _public(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _public(item)
            for key, item in cast(Mapping[Any, Any], value).items()
            if not _PRIVATE_OPTION.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_public(item) for item in cast(list[Any] | tuple[Any, ...], value)]
    return value


call_site: ContextVar[CallSite | None] = ContextVar("call_site", default=None)
_active: ContextVar[Attempt | None] = ContextVar("active_attempt", default=None)


def run_artifact[R](site: CallSite, make: Callable[[], R]) -> R:
    token = call_site.set(site)
    try:
        return make()
    finally:
        call_site.reset(token)


@contextmanager
def attempt(
    provider: Provider[Any],
    *,
    model: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    seed: int | None = None,
) -> Generator[Attempt]:
    result = Attempt()
    if (site := call_site.get()) is None:
        yield result
        return
    if (parent := _active.get()) is not None:
        parent.nested = True
    token = _active.set(result)
    started = monotonic()
    ts = datetime.now(UTC).isoformat()
    error: str | None = None
    try:
        yield result
    except BaseException as exc:
        # Provider diagnostics can contain raw replies or credentials.
        error = type(exc).__name__
        raise
    finally:
        _active.reset(token)
        if not result.nested:
            estimate = provider.cost.estimate(calls=1, output_seconds=result.output_seconds)
            configured_model = provider.options.get("model")
            record = {
                "ts": ts,
                "run_id": site.run_id,
                "stage": site.stage,
                "artifact": site.artifact,
                "provider": provider.name,
                "model": model or (configured_model if isinstance(configured_model, str) else None),
                "parameters": _public({**site.parameters, **(parameters or {})}),
                "seed": site.seed if seed is None else seed,
                "latency_s": monotonic() - started,
                "gpu_seconds": result.gpu_seconds,
                "cost_usd": 0.0,
                "list_price_usd": estimate.dollars or None,
                "outcome": "ok" if error is None else "error",
                "error": error,
            }
            with site.path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
