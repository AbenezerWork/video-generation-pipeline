"""JSON endpoints that read the project: ``GET /api/project`` and ``GET /api/run``."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from vidpipe.runstate import read_run_state
from vidpipe.ui.context import ui_context
from vidpipe.ui.summary import project_summary, run_state_json

NO_STORE = {"Cache-Control": "no-store"}


async def project(request: Request) -> JSONResponse:
    """The project summary: stages with provider and phase, gates, languages, and the run."""
    summary = await run_in_threadpool(project_summary, ui_context(request).project_dir)
    return JSONResponse(summary, headers=NO_STORE)


async def run(request: Request) -> JSONResponse:
    """The current run state (README, "Run state"), or ``null`` before the project's first run."""
    state = await run_in_threadpool(read_run_state, ui_context(request).project_dir)
    return JSONResponse(run_state_json(state), headers=NO_STORE)


def routes() -> list[Route]:
    return [
        Route("/api/project", project, methods=["GET"]),
        Route("/api/run", run, methods=["GET"]),
    ]
