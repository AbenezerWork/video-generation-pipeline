"""The stage detail's routes: a stage's outputs, its ledger records, the run log, ComfyUI's queue
and GPU stats, and the media files themselves.

- ``GET /api/stages/<stage>/outputs``: what the stage made (:func:`stage_outputs`) and its timing.
- ``GET /api/stages/<stage>/ledger``: the stage's ledger records (behind the disclosure).
- ``GET /api/logs``: the end of the run log; ``GET /api/comfyui``: ComfyUI's queue and GPUs (both
  behind the disclosure, fetched when it is opened).
- ``GET /media/build/...``, ``GET /media/out/...``: one media file of the project (see
  :func:`resolve_media`), with its content type and byte ranges for seeking.
"""

from __future__ import annotations

from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from vidpipe.ui.context import ui_context
from vidpipe.ui.diagnostics import comfyui_status, run_log
from vidpipe.ui.stage_outputs import (
    MEDIA_ROOTS,
    MEDIA_TYPES,
    StageNotFound,
    ledger_records,
    stage_outputs,
)

NO_STORE = {"Cache-Control": "no-store"}


def _not_found(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=404, headers=NO_STORE)


async def outputs(request: Request) -> JSONResponse:
    stage = request.path_params["stage"]
    try:
        detail = await run_in_threadpool(stage_outputs, ui_context(request).project_dir, stage)
    except StageNotFound:
        return _not_found(f"no stage named {stage!r}")
    return JSONResponse(detail, headers=NO_STORE)


async def ledger(request: Request) -> JSONResponse:
    stage = request.path_params["stage"]
    try:
        records = await run_in_threadpool(ledger_records, ui_context(request).project_dir, stage)
    except StageNotFound:
        return _not_found(f"no stage named {stage!r}")
    return JSONResponse({"stage": stage, "records": records}, headers=NO_STORE)


async def logs(request: Request) -> JSONResponse:
    log = await run_in_threadpool(run_log, ui_context(request).project_dir)
    return JSONResponse(log, headers=NO_STORE)


async def comfyui(request: Request) -> JSONResponse:
    status = await run_in_threadpool(comfyui_status, ui_context(request).project_dir)
    return JSONResponse(status, headers=NO_STORE)


def resolve_media(project_dir: Path, relative: str) -> Path | None:
    """The file ``relative`` names, if it is a media file inside the project's ``build/`` or
    ``out/`` folder; ``None`` for anything else (other folders, ``..``, absolute or Windows-only
    path forms, links leading outside, unknown types, missing files)."""
    parts = relative.split("/")
    if (
        not parts
        or parts[0] not in MEDIA_ROOTS
        or any(p in ("", ".", "..") for p in parts)
        or any(c in relative for c in "\\:\0")
        or Path(relative).suffix.lower() not in MEDIA_TYPES
    ):
        return None
    root = (project_dir / parts[0]).resolve()
    try:
        path = (project_dir / relative).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


async def media(request: Request) -> Response:
    relative = request.path_params["path"]
    path = await run_in_threadpool(resolve_media, ui_context(request).project_dir, relative)
    if path is None:
        return _not_found("no such media file in this project")
    _, content_type = MEDIA_TYPES[path.suffix.lower()]
    return FileResponse(
        path,
        media_type=content_type,
        # Files keep their names when a shot is redone: check with the server every time (the
        # ETag and Last-Modified make that cheap).
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


def routes() -> list[Route]:
    return [
        Route("/api/stages/{stage}/outputs", outputs, methods=["GET"]),
        Route("/api/stages/{stage}/ledger", ledger, methods=["GET"]),
        Route("/api/logs", logs, methods=["GET"]),
        Route("/api/comfyui", comfyui, methods=["GET"]),
        Route("/media/{path:path}", media, methods=["GET", "HEAD"]),
    ]
