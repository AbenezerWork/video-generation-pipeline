"""What the stage detail keeps behind its disclosure: the run log and ComfyUI's queue and GPUs.

Both are read only when asked for (the UI fetches them when the disclosure is opened), as plain
JSON-ready dicts (no web framework in here).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast

from vidpipe.comfy.client import DEFAULT_URL, ComfyClient, ComfyError
from vidpipe.project import Project, ProjectError
from vidpipe.runstate import Origin, read_run_state

#: Conventional location for a manually captured log.
RUN_LOG = "build/run.log"
#: How much of the end of the log is served.
LOG_LINES = 200
_LOG_TAIL_BYTES = 256 * 1024
#: How long to wait for ComfyUI before calling it unreachable.
COMFYUI_TIMEOUT_S = 2.0


def ui_log_path(run_id: str) -> Path:
    """Where a UI-started run logs, relative to the project root."""
    return Path("build") / "logs" / f"ui-run-{run_id}.log"


def read_log_tail(path: Path) -> tuple[str, bool]:
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        offset = max(0, size - _LOG_TAIL_BYTES)
        handle.seek(offset)
        tail = handle.read(_LOG_TAIL_BYTES).decode("utf-8", errors="replace")
    return tail, offset > 0


def run_log(project_dir: Path) -> dict[str, Any]:
    """The last :data:`LOG_LINES` lines of the current run's log."""
    state = read_run_state(project_dir)
    path = Path(RUN_LOG)
    if (
        state
        and state.origin == Origin.UI
        and re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{6}", state.run_id)
    ):
        path = ui_log_path(state.run_id)
    try:
        tail, truncated = read_log_tail(project_dir / path)
    except OSError:
        return {"path": path.as_posix(), "lines": [], "truncated": False}
    lines = tail.splitlines()
    if truncated:
        lines = lines[1:]  # the first line read was probably cut
    return {
        "path": path.as_posix(),
        "lines": lines[-LOG_LINES:],
        "truncated": truncated or len(lines) > LOG_LINES,
    }


def comfyui_url(project_dir: Path) -> str:
    try:
        configured = Project(project_dir).config.comfyui.url
    except ProjectError:
        configured = None
    return configured or DEFAULT_URL


def comfyui_status(project_dir: Path) -> dict[str, Any]:
    """The project's ComfyUI server: whether it answers, its queue and its GPUs with their memory.

    An unreachable server is a normal answer (``reachable`` false, ``error`` says why): ComfyUI
    runs outside vidpipe and is only needed by ``comfyui-*`` providers.
    """
    url = comfyui_url(project_dir)
    status: dict[str, Any] = {
        "url": url,
        "reachable": False,
        "version": None,
        "queue": None,
        "devices": [],
        "error": None,
    }
    try:
        client = ComfyClient(url, request_timeout_s=COMFYUI_TIMEOUT_S)
        stats = client.system_stats()
        running, pending = client.queue_counts()
    except (ComfyError, ValueError) as exc:
        status["error"] = str(exc)
        return status
    system = cast(dict[str, Any], stats.get("system") or {})
    devices = cast(list[dict[str, Any]], stats.get("devices") or [])
    status.update(
        reachable=True,
        version=system.get("comfyui_version"),
        queue={"running": running, "pending": pending},
        devices=[
            {
                key: device.get(key)
                for key in (
                    "name",
                    "type",
                    "vram_total",
                    "vram_free",
                    "torch_vram_total",
                    "torch_vram_free",
                )
            }
            for device in devices
            if device.get("type") != "cpu"
        ],
    )
    return status
