"""Run controls: start (optionally up to a stage), stop, stop now and resume, from the UI.

Routes (actions, answered with JSON):

- ``POST /api/run/start`` with ``{"until": <stage> | null}``: start a run, or resume one (a
  resumed run is an ordinary run that reuses finished work). ``202`` with ``run_id``, ``pid`` and
  ``log`` (the log file, relative to the project). ``409`` with ``error`` and ``holder`` while a
  run is in progress (``holder`` as in :class:`vidpipe.lock.RunInProgress`).
- ``POST /api/run/stop`` and ``POST /api/run/stop-now``: :func:`vidpipe.stop.request_stop`.
  Both accept an optional ``run_id`` to target a specific run. ``202`` with ``run_id`` and ``now``;
  ``409`` when the target run is no longer in progress.

Each run is a separate process running the normal CLI (``python -m vidpipe run``), with
``VIDPIPE_RUN_ORIGIN=ui``, fully detached from the server so it survives the browser closing and
the server quitting (Ctrl+C included):

- Windows: ``CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`` (and ``CREATE_BREAKAWAY_FROM_JOB``
  where the server's job allows it). The run gets a hidden console of its own, so a Ctrl+C or
  Ctrl+Break in the server's console never reaches it and the tools it starts (ffmpeg, text CLIs)
  open no windows. ``DETACHED_PROCESS`` is not used: without a console every console tool the run
  starts would open a window of its own.
- POSIX: ``start_new_session=True`` (``setsid``): a session and process group of its own, so the
  terminal's SIGINT and SIGHUP never reach it.

Stdin is a pipe closed at once (on Windows ``NUL`` can report itself as a terminal).
Gates pause the run as for any unattended run. Stdout and stderr go into a separate
log for each launch in ``build/logs/``.

Every action checks ``Origin`` (when sent) against the ``Host`` it was sent to, so another site
cannot make the browser start or stop runs.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO, cast
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from vidpipe.lock import RunInProgress, describe_holder, writer_lock
from vidpipe.runstate import ACTIVE, ORIGIN_ENV, RUN_ID_ENV, Origin, new_run_id, read_run_state
from vidpipe.stages import STAGE_NAMES
from vidpipe.stop import NoRunInProgress, request_stop
from vidpipe.ui.context import ui_context
from vidpipe.ui.diagnostics import read_log_tail, ui_log_path

#: How long ``start`` waits for the new run to publish its run state.
START_WAIT_S = 30.0

NO_STORE = {"Cache-Control": "no-store"}


class StartRefused(Exception):
    """The run could not start; ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int, holder: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.holder = holder


class RunLauncher:
    """Starts detached ``vidpipe run`` processes for one project, one at a time."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._run_id: str | None = None

    def start(self, until: str | None) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            holder = describe_holder(self.project_dir / "build")
            raise RunInProgress(self.project_dir, holder or "starting from the UI")
        try:
            # Fail fast with the usual message when another run (CLI or UI) holds the lock.
            with writer_lock(self.project_dir):
                if self._process is not None and self._process.poll() is None:
                    state = read_run_state(self.project_dir)
                    if state is None or state.run_id != self._run_id:
                        raise RunInProgress(self.project_dir, "starting from the UI")
            run_id = new_run_id()
            relative = ui_log_path(run_id)
            path = self.project_dir / relative
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8") as log:
                    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
                    scope = f" --until {until}" if until else ""
                    log.write(f"# vidpipe run{scope}, started from the UI at {stamp}\n")
                    log.flush()
                    self._process = process = _spawn(self.project_dir, run_id, until, log)
                    self._run_id = run_id
            except OSError as exc:
                raise StartRefused(f"could not launch vidpipe run: {exc}", 500) from exc
            # Reap completed children even if there is never another start request.
            threading.Thread(target=process.wait, daemon=True).start()
            return self._started(process, run_id, relative)
        finally:
            self._lock.release()

    def _started(
        self, process: subprocess.Popen[bytes], run_id: str, relative: Path
    ) -> dict[str, Any]:
        """Wait until the new run has published its run state, or has exited without one."""
        log = relative.as_posix()
        deadline = time.monotonic() + START_WAIT_S
        while time.monotonic() < deadline:
            exited = process.poll() is not None
            state = read_run_state(self.project_dir)
            if state is not None and state.run_id == run_id:
                return {"run_id": run_id, "pid": state.pid, "log": log}
            if exited:
                break
            time.sleep(0.05)
        else:
            return {"run_id": run_id, "pid": None, "log": log}  # still starting
        last = _last_line(self.project_dir / relative)
        if "a run is in progress" in last:  # another run took the lock first
            holder = describe_holder(self.project_dir / "build")
            raise StartRefused(last.removeprefix("error: "), 409, holder)
        raise StartRefused(last.removeprefix("error: ") or "the run exited on start", 500)


def _last_line(path: Path) -> str:
    with contextlib.suppress(OSError):
        lines = [line for line in read_log_tail(path)[0].splitlines() if line.strip()]
        if lines:
            return lines[-1].strip()
    return ""


def _spawn(
    project_dir: Path, run_id: str, until: str | None, log: TextIO
) -> subprocess.Popen[bytes]:
    command = [sys.executable, "-m", "vidpipe", "run", str(project_dir)]
    if until:
        command += ["--until", until]
    env = {
        **os.environ,
        ORIGIN_ENV: Origin.UI.value,
        RUN_ID_ENV: run_id,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

    def launch(creationflags: int) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=project_dir,
            close_fds=True,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
        )

    if not flags:
        process = launch(0)
    else:
        try:
            process = launch(flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except PermissionError:  # the server's job does not allow breaking away
            process = launch(flags)
    assert process.stdin is not None
    process.stdin.close()  # end of file: the run never waits for input
    return process


# ---------------------------------------------------------------- routes


def _error(message: str, status: int, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status, headers=NO_STORE)


def same_origin_only(
    action: Callable[[Request], Awaitable[JSONResponse]],
) -> Callable[[Request], Awaitable[JSONResponse]]:
    """Refuse an action whose ``Origin`` is another site (a browser always sends it on POST)."""

    async def guarded(request: Request) -> JSONResponse:
        origin = request.headers.get("origin")
        if origin is not None:
            try:
                expected = f"{request.url.scheme}://{request.headers.get('host')}"
                same_origin = urlsplit(origin) == urlsplit(expected)
            except ValueError:
                same_origin = False
            if not same_origin:
                return _error("actions are only accepted from the vidpipe UI's own page", 403)
        return await action(request)

    return guarded


async def _body(request: Request) -> dict[str, Any] | None:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        body = await request.json()
    except ValueError:
        return None
    return cast(dict[str, Any], body) if isinstance(body, dict) else None


@same_origin_only
async def start(request: Request) -> JSONResponse:
    body = await _body(request)
    if body is None:
        return _error("expected a JSON object", 400)
    until = body.get("until")
    if until is not None and (not isinstance(until, str) or until not in STAGE_NAMES):
        return _error(f"until must be one of: {', '.join(STAGE_NAMES)}", 400)
    launcher: RunLauncher = request.app.state.run_launcher
    try:
        started = await run_in_threadpool(launcher.start, until)
    except RunInProgress as exc:
        return _error(str(exc), 409, holder=exc.holder)
    except StartRefused as exc:
        return _error(str(exc), exc.status, holder=exc.holder)
    except OSError as exc:
        return _error(f"could not start the run: {exc}", 500)
    return JSONResponse(started, status_code=202, headers=NO_STORE)


async def _stop(request: Request, *, now: bool) -> JSONResponse:
    body = await _body(request)
    if body is None:
        return _error("expected a JSON object", 400)
    run_id = body.get("run_id")
    if run_id is not None and not isinstance(run_id, str):
        return _error("run_id must be a string", 400)
    project_dir = ui_context(request).project_dir
    try:
        asked = await run_in_threadpool(request_stop, project_dir, now=now, run_id=run_id)
    except NoRunInProgress as exc:
        return _error(str(exc), 409)
    except OSError as exc:
        return _error(f"could not write the stop request: {exc}", 500)
    return JSONResponse(
        {"run_id": asked.run_id, "now": asked.now}, status_code=202, headers=NO_STORE
    )


@same_origin_only
async def stop(request: Request) -> JSONResponse:
    return await _stop(request, now=False)


@same_origin_only
async def stop_now(request: Request) -> JSONResponse:
    return await _stop(request, now=True)


def routes() -> list[Route]:
    return [
        Route("/api/run/start", start, methods=["POST"]),
        Route("/api/run/stop", stop, methods=["POST"]),
        Route("/api/run/stop-now", stop_now, methods=["POST"]),
    ]


# ---------------------------------------------------------------- quitting the server


def ask_on_quit(project_dir: Path) -> None:
    """When the server quits with a run in progress, ask whether to leave it going or stop it.

    The default (Enter, end of input, a second Ctrl+C, or no terminal at all) leaves it going;
    nothing is asked when stdin is not a terminal, so an unattended server never hangs here.
    """
    stdin, out = sys.stdin, sys.stdout
    if out is None:
        return
    state = read_run_state(project_dir)
    if state is None or state.status not in ACTIVE:
        return
    answer = ""
    if stdin is not None and stdin.isatty():
        out.write("\nA run is in progress. Leave it running, or stop it? [L/s] ")
        out.flush()
        try:
            answer = stdin.readline().strip().lower()
        except (KeyboardInterrupt, EOFError, OSError):
            answer = ""
    if answer in ("s", "stop"):
        with contextlib.suppress(NoRunInProgress):
            request_stop(project_dir, run_id=state.run_id)
            out.write("Stopping the run after the artifact in progress.\n")
            out.flush()
            return
    out.write(
        f"The run keeps going (process {state.pid}). Stop it with: vidpipe stop {project_dir}\n"
    )
    out.flush()
