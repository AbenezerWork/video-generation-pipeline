"""The Config view's endpoints.

- ``GET /api/config``: the project config file as a document, its schema, and its check.
- ``POST /api/config/validate`` ``{"document": ...}``: the check of a document not yet saved
  (errors by setting path, the YAML saving would write, the config as the CLI reads it).
- ``GET /api/providers``: each stage's provider choices with options and doctor readiness.
- ``POST /api/providers/check`` ``{"document": ...}``: the same for a document not yet saved.

Nothing here writes to the project.
"""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from vidpipe.ui.config_form import check_config, config_schema, read_document
from vidpipe.ui.context import ui_context
from vidpipe.ui.provider_choices import provider_choices

NO_STORE = {"Cache-Control": "no-store"}


def _foreign_origin(request: Request) -> bool:
    """A POST from another site's page (browsers send ``Origin`` on every POST)."""
    origin = request.headers.get("origin")
    return origin is not None and urlsplit(origin).netloc != request.headers.get("host")


async def _document(request: Request) -> tuple[Any, JSONResponse | None]:
    if _foreign_origin(request):
        return None, JSONResponse({"error": "cross-site request refused"}, status_code=403)
    try:
        body = await request.json()
    except ValueError:
        return None, JSONResponse({"error": "the body must be JSON"}, status_code=400)
    if not isinstance(body, dict) or "document" not in body:
        return None, JSONResponse({"error": 'send {"document": {...}}'}, status_code=400)
    return cast(dict[str, Any], body).get("document"), None


def _view(request: Request) -> dict[str, Any]:
    project_dir = ui_context(request).project_dir
    document, problem = read_document(project_dir)
    check = check_config(project_dir, document) if document is not None else None
    return {
        "document": document,
        "problem": problem,
        "schema": config_schema(),
        "check": check.to_json() if check is not None else None,
    }


async def config(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(_view, request), headers=NO_STORE)


async def validate(request: Request) -> JSONResponse:
    document, refused = await _document(request)
    if refused is not None:
        return refused
    check = await run_in_threadpool(check_config, ui_context(request).project_dir, document)
    return JSONResponse(check.to_json(), headers=NO_STORE)


async def providers(request: Request) -> JSONResponse:
    choices = await run_in_threadpool(provider_choices, ui_context(request).project_dir)
    return JSONResponse(choices, headers=NO_STORE)


async def check_providers(request: Request) -> JSONResponse:
    document, refused = await _document(request)
    if refused is not None:
        return refused
    choices = await run_in_threadpool(provider_choices, ui_context(request).project_dir, document)
    return JSONResponse(choices, headers=NO_STORE)


def routes() -> list[Route]:
    return [
        Route("/api/config", config, methods=["GET"]),
        Route("/api/config/validate", validate, methods=["POST"]),
        Route("/api/providers", providers, methods=["GET"]),
        Route("/api/providers/check", check_providers, methods=["POST"]),
    ]
