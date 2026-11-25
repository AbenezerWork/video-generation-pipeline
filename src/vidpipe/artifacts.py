"""Content-hashed artifacts: the ledger behind skip-unchanged, resume and re-roll.

Every generated artifact is produced through :meth:`ArtifactStore.produce`. The caller names the
artifact (``key``), declares what it depends on (:class:`Inputs`: upstream files, hashed by content,
and plain values) and supplies a function that generates it. The store hashes the declared inputs
together with the provider's identity, the parameters and the seed. When the ledger already holds a
record with the same input hash and its output files still exist, the function is not called and
the recorded result is returned instead. Otherwise it runs, and a record (provider, parameters,
seed, GPU time, timing, output hashes) is saved atomically before the next artifact starts, so a
killed run loses at most the artifact that was in flight.

Because inputs are hashed by *content*, a regenerated upstream artifact that comes out identical
does not invalidate anything downstream, and a hand-edited artifact (say ``build/script.json``)
changes the hash of exactly the artifacts that read it. An artifact whose own inputs are unchanged
is never overwritten, so hand edits to it survive until its inputs change.

State lives in ``build/ledger.json``. Keys follow ``<stage>`` or ``<stage>/<unit>`` (for example
``narration/en/shot_03``, ``keyframes/shot_07``) so a later re-roll can forget one by key.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from vidpipe.contracts import Provider
from vidpipe.project import Project

#: Bump when the hashing scheme changes; an older ledger is then ignored (everything regenerates).
LEDGER_VERSION = 1
LEDGER_FILENAME = "ledger.json"


class OutputFile(BaseModel):
    path: str  # relative to the project root, posix separators
    sha256: str
    size: int


class ArtifactRecord(BaseModel):
    """What was generated, from what, by whom, and what it cost."""

    key: str
    stage: str
    input_hash: str
    #: Label -> content hash (or value digest) of every declared input; explains a re-run.
    inputs: dict[str, str]
    provider: str | None
    provider_options: dict[str, Any] = Field(default_factory=dict[str, Any])
    parameters: dict[str, Any] = Field(default_factory=dict[str, Any])
    seed: int | None = None
    #: Seconds of local GPU time (wall time of the provider call when the provider runs on the GPU).
    gpu_seconds: float = 0.0
    wall_seconds: float = 0.0
    started_at: str
    outputs: list[OutputFile]
    #: Small result values the stage needs again when it skips (durations, sizes, ...).
    data: dict[str, Any] = Field(default_factory=dict[str, Any])
    #: Any recorded quality step-down applied to produce this artifact (e.g. after OOM).
    fallback: str | None = None


class Ledger(BaseModel):
    version: int = LEDGER_VERSION
    artifacts: dict[str, ArtifactRecord] = Field(default_factory=dict[str, ArtifactRecord])
    #: Times each shot (`shot_NN`) has been re-rolled with `vidpipe redo`; feeds its seeds.
    rerolls: dict[str, int] = Field(default_factory=dict[str, int])


@dataclass(frozen=True)
class Inputs:
    """What an artifact depends on.

    ``files`` are upstream files (a ``str`` is relative to ``build/``, a ``Path`` is used as given)
    and are hashed by content. ``values`` are plain JSON-able values (text, sizes, durations...).
    Never put absolute paths in ``values``: they would tie hashes to one checkout.
    """

    files: Sequence[str | Path] = ()
    values: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass
class Made:
    """What a ``produce`` function returns: the files it wrote and any small result data."""

    outputs: Sequence[str | Path]
    data: dict[str, Any] = field(default_factory=dict[str, Any])
    #: Exact GPU seconds when the provider reports them; otherwise measured from the call.
    gpu_seconds: float | None = None
    #: A recorded quality step-down (e.g. lower resolution after an out-of-memory error).
    fallback: str | None = None


@dataclass
class Produced:
    paths: list[Path]  # absolute
    data: dict[str, Any]
    reused: bool
    record: ArtifactRecord


# ------------------------------------------------------------------------------------- hashing


def _normalise(value: Any) -> Any:
    """JSON-able, order-independent form of a value (sets are sorted, models dumped)."""
    if isinstance(value, BaseModel):
        return _normalise(value.model_dump())
    if isinstance(value, Enum):
        return _normalise(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(k): _normalise(v) for k, v in cast(Mapping[Any, Any], value).items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_normalise(v) for v in cast(set[Any], value)), key=_canonical)
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in cast(list[Any], value)]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        _normalise(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


# ------------------------------------------------------------------------------------- the store


class ArtifactStore:
    """Reads and writes ``build/ledger.json`` and runs artifacts through the hash check."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.path = project.build / LEDGER_FILENAME
        self._ledger: Ledger | None = None
        self._file_hashes: dict[tuple[str, int, int], str] = {}

    # -------------------------------------------------------------------------------- ledger

    @property
    def ledger(self) -> Ledger:
        if self._ledger is None:
            self._ledger = self._load()
        return self._ledger

    def _load(self) -> Ledger:
        try:
            ledger = Ledger.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Ledger()
        return ledger if ledger.version == LEDGER_VERSION else Ledger()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(self.ledger.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: a kill never leaves a half-written ledger

    def record(self, key: str) -> ArtifactRecord | None:
        return self.ledger.artifacts.get(key)

    def shot_seed(self, shot_id: int) -> int:
        """Seed for a shot's keyframe and video: the shot id until it is re-rolled, then a new
        deterministic value for each re-roll (the count is in the ledger, the seed in each record).
        """
        count = self.ledger.rerolls.get(f"shot_{shot_id:02d}", 0)
        if count == 0:
            return shot_id
        return int(digest(["reroll", shot_id, count])[:8], 16) % 2**31

    def reroll_shot(self, shot_id: int) -> int:
        """Count one more re-roll of the shot (saved at once); returns its new seed."""
        key = f"shot_{shot_id:02d}"
        self.ledger.rerolls[key] = self.ledger.rerolls.get(key, 0) + 1
        self._save()
        return self.shot_seed(shot_id)

    def forget(self, key_prefix: str) -> list[str]:
        """Drop the records for ``key_prefix`` and all under it; the next run regenerates them."""
        gone = [
            k
            for k in self.ledger.artifacts
            if k == key_prefix or k.startswith(key_prefix.rstrip("/") + "/")
        ]
        for key in gone:
            del self.ledger.artifacts[key]
        if gone:
            self._save()
        return gone

    # ------------------------------------------------------------------------------ locating

    def locate(self, path: str | Path) -> Path:
        """Absolute path: a ``str`` is relative to ``build/``, a ``Path`` is used as given."""
        return path if isinstance(path, Path) else self.project.build / path

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.project.root).as_posix()

    def hash_path(self, path: Path) -> str:
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        cached = self._file_hashes.get(key)
        if cached is None:
            cached = self._file_hashes[key] = hash_file(path)
        return cached

    # ------------------------------------------------------------------------------- produce

    def input_map(self, inputs: Inputs) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for item in inputs.files:
            path = self.locate(item)
            label = f"file:{self._rel(path)}"
            mapped[label] = self.hash_path(path) if path.is_file() else "missing"
        for name, value in inputs.values.items():
            mapped[f"value:{name}"] = digest(value)
        return mapped

    def input_hash(
        self,
        *,
        stage: str,
        provider: Provider[Any] | None,
        options: Mapping[str, Any],
        inputs: Mapping[str, str],
        parameters: Mapping[str, Any],
        seed: int | None,
    ) -> str:
        return digest(
            {
                "ledger": LEDGER_VERSION,
                "stage": stage,
                "provider": provider.fingerprint() if provider else None,
                "options": options,
                "inputs": inputs,
                "parameters": parameters,
                "seed": seed,
            }
        )

    def produce(
        self,
        key: str,
        *,
        stage: str,
        provider: Provider[Any] | None,
        inputs: Inputs,
        make: Callable[[], Made],
        options: Mapping[str, Any] | None = None,
        parameters: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> Produced:
        """Return the artifact ``key``, generating it with ``make`` only when its inputs changed.

        ``options`` are the provider options from the project config: they are hashed and recorded
        (a provider may consume them in its constructor, so ``provider.options`` is not enough).
        The provider's ``unhashed_options`` (a server address, say) are recorded but not hashed.
        """
        params = dict(parameters or {})
        configured = dict(options or {})
        mapped = self.input_map(inputs)
        unhashed: frozenset[str] = provider.unhashed_options if provider else frozenset()
        wanted = self.input_hash(
            stage=stage,
            provider=provider,
            options={k: v for k, v in configured.items() if k not in unhashed},
            inputs=mapped,
            parameters=params,
            seed=seed,
        )
        existing = self.record(key)
        if (
            existing is not None
            and existing.input_hash == wanted
            and all(self.project.root.joinpath(o.path).is_file() for o in existing.outputs)
        ):
            paths = [self.project.root / o.path for o in existing.outputs]
            return Produced(paths=paths, data=existing.data, reused=True, record=existing)

        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        clock = time.perf_counter()
        made = make()
        wall = time.perf_counter() - clock

        paths = [self.locate(o) for o in made.outputs]
        record = ArtifactRecord(
            key=key,
            stage=stage,
            input_hash=wanted,
            inputs=mapped,
            provider=provider.name if provider else None,
            provider_options=configured if provider else {},
            parameters=params,
            seed=seed,
            gpu_seconds=(
                made.gpu_seconds
                if made.gpu_seconds is not None
                else wall
                if provider is not None and provider.uses_gpu
                else 0.0
            ),
            wall_seconds=wall,
            started_at=started_at,
            outputs=[
                OutputFile(path=self._rel(p), sha256=self.hash_path(p), size=p.stat().st_size)
                for p in paths
            ],
            data=made.data,
            fallback=made.fallback,
        )
        self.ledger.artifacts[key] = record
        self._save()
        return Produced(paths=paths, data=made.data, reused=False, record=record)
