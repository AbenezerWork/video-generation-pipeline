"""The run state: what a run in progress is doing right now, published in ``build/run_state.json``.

The runner rewrites the file atomically (a temporary file renamed over it) when the run starts,
when a stage begins, after each artifact (at most every :data:`PROGRESS_INTERVAL_S`) and when a
stage or the run ends. Readers (``vidpipe.lock``'s refusal message, the UI) only ever see a whole
record. The file stays behind after the run as the record of how the last run ended. The schema
is documented in the README ("Run state").
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from vidpipe.config import ProjectConfig
from vidpipe.project import Project

RUN_STATE_FILENAME = "run_state.json"
#: Environment variable naming who started the run (``cli`` or ``ui``); the UI sets it to ``ui``.
ORIGIN_ENV = "VIDPIPE_RUN_ORIGIN"
#: Version of the record's schema, bumped on incompatible changes.
SCHEMA_VERSION = 1
#: Progress after an artifact is written at most this often; stage and run changes always are.
PROGRESS_INTERVAL_S = 0.25


class Origin(StrEnum):
    CLI = "cli"
    UI = "ui"


class RunStatus(StrEnum):
    RUNNING = "running"
    #: A stop was asked for; the run ends after the artifact in progress (ticket 03).
    STOPPING = "stopping"
    #: Held at a gate, waiting for approval.
    PAUSED = "paused"
    FAILED = "failed"
    FINISHED = "finished"
    STOPPED = "stopped"


#: Statuses of a run that is still going.
ACTIVE = (RunStatus.RUNNING, RunStatus.STOPPING)


class StageStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    #: Finished, generating at least one artifact.
    DONE = "done"
    #: Finished, every artifact reused from an earlier run.
    REUSED = "reused"
    #: Finished; its gate holds the run.
    PAUSED = "paused"
    FAILED = "failed"
    STOPPED = "stopped"


class StageProgress(BaseModel):
    stage: str
    #: The provider the project config chose (``None`` for stages without one).
    provider: str | None = None
    status: StageStatus = StageStatus.WAITING
    #: Artifacts finished so far (``generated + reused``) and expected in all; ``total`` is
    #: ``None`` until it can be worked out from what earlier stages wrote.
    done: int = 0
    total: int | None = None
    generated: int = 0
    reused: int = 0
    started_at: str | None = None
    finished_at: str | None = None


class RunError(BaseModel):
    #: The stage that failed; ``None`` when the run failed before any stage (at plan time).
    stage: str | None
    message: str


class RunState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    #: ``run`` or ``redo`` (then ``shot`` is the re-rolled shot).
    command: str = "run"
    shot: int | None = None
    origin: Origin
    pid: int
    #: ISO 8601 local time with UTC offset.
    started_at: str
    updated_at: str
    finished_at: str | None = None
    #: Goes up by one on every write, so a reader can tell a new record from one it has seen.
    seq: int = 0
    status: RunStatus = RunStatus.RUNNING
    #: The last stage the run was asked for (``--until``); ``None`` means every stage.
    until: str | None = None
    #: The stage running now; ``None`` before the first stage and once the run has ended.
    current_stage: str | None = None
    #: The gate holding the run when ``status`` is ``paused``.
    paused_at: str | None = None
    #: :func:`config_hash` of the project config the run started with.
    config_hash: str
    #: The stages this run covers, in run order.
    stages: list[StageProgress] = Field(default_factory=list[StageProgress])
    error: RunError | None = None

    def stage(self, name: str) -> StageProgress:
        return next(s for s in self.stages if s.stage == name)


def config_hash(config: ProjectConfig | Path) -> str:
    """Fingerprint of a project config (or a project directory's), as recorded in the run state.

    It hashes the validated config, so comments and formatting do not count as a change.
    """
    if isinstance(config, Path):
        config = Project(config).config
    return hashlib.sha256(config.model_dump_json().encode("utf-8")).hexdigest()


def resolve_origin(origin: Origin | str | None = None) -> Origin:
    """``origin``, else ``$VIDPIPE_RUN_ORIGIN``, else ``cli``; raises ``ValueError`` if unknown."""
    value = origin or os.environ.get(ORIGIN_ENV) or Origin.CLI
    try:
        return Origin(value)
    except ValueError:
        choices = ", ".join(o.value for o in Origin)
        message = f"{ORIGIN_ENV}: unknown run origin {value!r} (one of: {choices})"
        raise ValueError(message) from None


def write_atomically(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` via a temporary file, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        for attempt in range(100):
            try:
                os.replace(temp, path)
                break
            except PermissionError:  # Windows: a reader has the file open right now
                if attempt == 99:
                    raise
                time.sleep(0.02)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_run_state(project_dir: Path) -> RunState | None:
    """The last run state of a project (``None`` if no run has recorded one).

    A record still saying ``running`` or ``stopping`` whose process is gone (killed, crashed) is
    returned as ``failed``, with an error saying the process ended and the stage it was in marked
    ``failed``; the file is left as it is.
    """
    path = project_dir / "build" / RUN_STATE_FILENAME
    state = None
    for _ in range(20):  # a rename can briefly deny access on Windows; never a torn record
        try:
            state = RunState.model_validate_json(path.read_bytes())
            break
        except FileNotFoundError:
            return None
        except (PermissionError, ValidationError):
            time.sleep(0.01)
    if state is None:
        return None
    if state.status in ACTIVE and not _alive(state.pid):
        state.status = RunStatus.FAILED
        if state.current_stage is not None:  # the stage it was in failed with it
            state.stage(state.current_stage).status = StageStatus.FAILED
        state.error = RunError(
            stage=state.current_stage, message=f"the run's process ({state.pid}) ended unexpectedly"
        )
        state.current_stage = None
    return state


def _alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunStatePublisher:
    """The runner's side: keeps a :class:`RunState` and writes it to ``build/run_state.json``."""

    def __init__(
        self,
        project: Project,
        *,
        origin: Origin,
        stages: list[tuple[str, str | None]],
        until: str | None = None,
        command: str = "run",
        shot: int | None = None,
    ) -> None:
        self.path = project.build / RUN_STATE_FILENAME
        now = _now()
        self.state = RunState(
            run_id=f"{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}",
            command=command,
            shot=shot,
            origin=origin,
            pid=os.getpid(),
            started_at=now,
            updated_at=now,
            until=until,
            config_hash=config_hash(project.config),
            stages=[StageProgress(stage=name, provider=provider) for name, provider in stages],
        )
        self._last_write = 0.0
        self._lock = threading.RLock()
        self.write()

    # ------------------------------------------------------------------ what the runner reports
    # A stop request is seen by a watcher thread (``vidpipe.stop``), so every change and write
    # holds ``_lock``.

    def totals(self, totals: dict[str, int | None]) -> None:
        """Expected artifact counts of stages still waiting, as far as they are known (written
        with the next change)."""
        with self._lock:
            for name, total in totals.items():
                stage = self.state.stage(name)
                if stage.status == StageStatus.WAITING:
                    stage.total = total

    def begin_stage(self, name: str, total: int | None) -> None:
        with self._lock:
            stage = self.state.stage(name)
            stage.status, stage.started_at = StageStatus.RUNNING, _now()
            stage.done = stage.generated = stage.reused = 0
            if total is not None:
                stage.total = total
            self.state.current_stage = name
            self.write()

    def artifact(self, generated: int, reused: int) -> None:
        """An artifact of the current stage finished; written at most every interval."""
        with self._lock:
            if self.state.current_stage is None:
                return
            stage = self.state.stage(self.state.current_stage)
            stage.generated, stage.reused, stage.done = generated, reused, generated + reused
            if time.monotonic() - self._last_write >= PROGRESS_INTERVAL_S:
                self.write()

    def end_stage(self, name: str, generated: int, reused: int, *, paused: bool = False) -> None:
        with self._lock:
            stage = self.state.stage(name)
            stage.generated, stage.reused, stage.done = generated, reused, generated + reused
            if stage.total is None or stage.total < stage.done:
                stage.total = stage.done
            if paused:
                stage.status = StageStatus.PAUSED
            elif generated == 0 and reused > 0:
                stage.status = StageStatus.REUSED
            else:
                stage.status = StageStatus.DONE
            stage.finished_at = _now()
            self.write()

    def stopping(self) -> None:
        """A stop was asked for: the run goes on to the end of the artifact in progress."""
        with self._lock:
            if self.state.status == RunStatus.RUNNING:
                self.state.status = RunStatus.STOPPING
                self.write()

    def finish(self, *, paused_at: str | None = None) -> None:
        with self._lock:
            self.state.paused_at = paused_at
            self._end(RunStatus.PAUSED if paused_at else RunStatus.FINISHED)

    def stop(self, generated: int = 0, reused: int = 0) -> None:
        """The run stopped as asked; the stage in progress (if any) is marked stopped, with the
        ``generated`` and ``reused`` artifacts it finished."""
        with self._lock:
            name = self.state.current_stage
            if name is not None:
                stage = self.state.stage(name)
                stage.generated, stage.reused, stage.done = generated, reused, generated + reused
                stage.status, stage.finished_at = StageStatus.STOPPED, _now()
            self._end(RunStatus.STOPPED)

    def fail(self, message: str) -> None:
        """The run ended with an error; the stage in progress (if any) is marked failed."""
        with self._lock:
            name = self.state.current_stage
            if name is not None:
                stage = self.state.stage(name)
                stage.status, stage.finished_at = StageStatus.FAILED, _now()
            self.state.error = RunError(stage=name, message=message)
            self._end(RunStatus.FAILED)

    def _end(self, status: RunStatus) -> None:
        self.state.status = status
        self.state.current_stage = None
        self.state.finished_at = _now()
        self.write()

    # ------------------------------------------------------------------ the file

    def write(self) -> None:
        """Replace the file with the current record, atomically."""
        with self._lock:
            self.state.seq += 1
            self.state.updated_at = _now()
            write_atomically(self.path, self.state.model_dump_json(indent=2).encode("utf-8"))
            self._last_write = time.monotonic()
