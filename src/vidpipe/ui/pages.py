"""The console page (``/``) and the static front end (``/static/...``)."""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

STATIC = Path(__file__).resolve().parent / "static"


async def console(request: Request) -> FileResponse:
    """The console page; its script fills it from ``/api/project`` and ``/api/events``."""
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


def routes() -> list[BaseRoute]:
    return [
        Route("/", console, methods=["GET"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
