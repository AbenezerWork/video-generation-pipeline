"""Stop and stop now: asking a run in progress to end, from outside it.

A **stop** ends the run once the artifact in progress finishes, so no finished work is lost. A
**stop now** also cancels the ComfyUI job in progress and discards that one artifact (a provider
that cannot drop its work, a text CLI say, finishes the artifact as for a stop). Either way the run
ends with status ``stopped``, and resuming is an ordinary run that reuses what was finished.

The request is a file, ``build/stop_request.json``, naming the run it is for: the requester
(``vidpipe stop``, the UI's server) writes it without the project's one-writer lock, which the run
holds. The run watches for it (:class:`StopWatcher`), marks itself ``stopping`` in the run state,
acts on it and removes it when it ends. Only the run writes the run state. A request naming
another run (one that already ended) is ignored.
"""

from __future__ import annotations

import contextlib
import threading
import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from vidpipe.project import ProjectError
from vidpipe.runstate import ACTIVE, RunStatePublisher, read_run_state, write_atomically

STOP_REQUEST_FILENAME = "stop_request.json"
#: Exit code of ``vidpipe run`` / ``redo`` when the run stopped as asked.
EXIT_STOPPED = 4
#: How often the run looks for a request.
POLL_S = 0.1


class NoRunInProgress(ProjectError):
    """There is no run to stop."""


class StopRequest(BaseModel):
    #: The run it is for (``run_id`` of its run state).
    run_id: str
    #: Stop now: cancel the ComfyUI job in progress instead of waiting for it.
    now: bool = False
    requested_at: str


class RunStopped(Exception):  # noqa: N818 (an outcome, not an error)
    """Raised in the runner between artifacts once a stop was asked for."""


def request_stop(project_dir: Path, *, now: bool = False) -> StopRequest:
    """Ask the run in progress on ``project_dir`` to stop (``now``: stop now).

    Does not take the project lock. Raises :class:`NoRunInProgress` when no run is in progress.
    Asking again is harmless; a stop now after a stop turns it into a stop now (never back).
    Returns the request written; the run state shows ``stopping`` once the run has seen it.
    """
    root = Path(project_dir)
    state = read_run_state(root)
    if state is None or state.status not in ACTIVE:
        raise NoRunInProgress(f"{root}: no run in progress to stop")
    path = root / "build" / STOP_REQUEST_FILENAME
    earlier = _read(path)
    already_now = earlier is not None and earlier.run_id == state.run_id and earlier.now
    asked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    request = StopRequest(run_id=state.run_id, now=now or already_now, requested_at=asked_at)
    write_atomically(path, request.model_dump_json(indent=2).encode("utf-8"))
    return request


def _read(path: Path) -> StopRequest | None:
    try:
        return StopRequest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError):  # absent, or briefly locked by a rename on Windows
        return None


class StopWatcher:
    """The runner's side: a thread that looks for a request for this run every :data:`POLL_S`.

    On seeing one it marks the run state ``stopping``. The runner calls :meth:`check` between
    artifacts and before each stage; providers poll :meth:`now_requested` while they wait.
    """

    def __init__(self, build: Path, state: RunStatePublisher) -> None:
        self.path = build / STOP_REQUEST_FILENAME
        self._state = state
        self._run_id = state.state.run_id
        self._requested = threading.Event()
        self._now = threading.Event()
        self._done = threading.Event()
        self._remove()  # a request left by an earlier run is not for this one
        self._thread = threading.Thread(target=self._watch, name="vidpipe-stop", daemon=True)
        self._thread.start()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def now_requested(self) -> bool:
        return self._now.is_set()

    def check(self) -> None:
        """Raise :class:`RunStopped` if a stop was asked for."""
        self._look()
        if self.requested:
            raise RunStopped

    def close(self) -> None:
        """Stop watching and remove this run's request (the run has ended)."""
        self._done.set()
        self._thread.join(timeout=5)
        request = _read(self.path)
        if request is None or request.run_id == self._run_id:
            self._remove()

    def _watch(self) -> None:
        while not self._done.wait(POLL_S):
            self._look()

    def _look(self) -> None:
        if self.now_requested():
            return
        request = _read(self.path)
        if request is None or request.run_id != self._run_id:
            return
        if request.now:
            self._now.set()
        if not self._requested.is_set():
            self._requested.set()
            self._state.stopping()

    def _remove(self) -> None:
        for _ in range(20):
            try:
                self.path.unlink(missing_ok=True)
                return
            except PermissionError:  # Windows: the requester is replacing it right now
                time.sleep(0.02)
        with contextlib.suppress(OSError):
            self.path.unlink(missing_ok=True)
