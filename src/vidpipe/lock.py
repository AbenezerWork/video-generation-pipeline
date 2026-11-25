"""The one-writer lock: at most one run (or ``redo``, or ``approve``) writes to a project at a time.

The lock is an OS file lock (``filelock``: ``LockFileEx`` on Windows, ``flock`` elsewhere) on
``build/run.lock``, held for the whole command. The OS lets go of it when the holding process
ends, however it ends, so a killed or crashed run never leaves a lock that blocks the next one.
The file itself stays behind and means nothing on its own: only a held lock counts.

Projects on network drives are unsupported: their file locks are not reliable.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from vidpipe.project import ProjectError

LOCK_FILENAME = "run.lock"


class RunInProgress(ProjectError):
    """Another process holds the project's one-writer lock: a run is in progress."""

    def __init__(self, root: Path, holder: str | None = None) -> None:
        self.root = root
        self.holder = holder
        who = f" ({holder})" if holder else ""
        super().__init__(
            f"{root}: a run is in progress on this project{who}. "
            "Wait for it to finish, then try again."
        )


def describe_holder(build: Path) -> str | None:
    """Who holds the lock and since when, for the refusal message; ``None`` when unknown.

    Seam for the run state: nothing records the holder yet, so the message names nobody.
    """
    del build
    return None


@contextmanager
def writer_lock(root: Path) -> Generator[None]:
    """Hold the project's one-writer lock for the ``with`` block, or raise :class:`RunInProgress`.

    Fails fast: a second writer never waits for the first. Not re-entrant across calls; take it
    once per command.
    """
    build = root / "build"
    build.mkdir(parents=True, exist_ok=True)
    # No soft (marker-file) fallback: a marker outlives a killed process, an OS lock does not.
    lock = FileLock(
        build / LOCK_FILENAME, timeout=0, fallback_to_soft=False, preserve_lock_file=True
    )
    try:
        lock.acquire()
    except Timeout:
        raise RunInProgress(root, describe_holder(build)) from None
    try:
        yield
    finally:
        lock.release()
