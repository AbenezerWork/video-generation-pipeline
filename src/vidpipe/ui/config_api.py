"""The Config view's endpoints.

- ``GET /api/config``: the project config file as a document, its schema, and its check.
- ``POST /api/config/validate`` ``{"document": ...}``: the check of a document not yet saved
  (errors by setting path, the YAML saving would write, the config as the CLI reads it).
- ``POST /api/config/save``: validate and atomically save a document, optionally matching the
  revision returned by ``GET /api/config``.
- ``POST /api/config/plan``: the CLI plan and the regeneration estimate for a proposed document.
- ``GET /api/providers``: each stage's provider choices with options and doctor readiness.
- ``POST /api/providers/check`` ``{"document": ...}``: the same for a document not yet saved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from filelock import FileLock, Timeout
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from vidpipe.config import CONFIG_FILENAME, ProjectConfig
from vidpipe.pipeline import plan
from vidpipe.runstate import ACTIVE, config_hash, read_run_state, write_atomically
from vidpipe.ui.config_form import check_config, config_schema, read_document, revision_of
from vidpipe.ui.context import ui_context
from vidpipe.ui.provider_choices import provider_choices
from vidpipe.ui.runs import same_origin_only

NO_STORE = {"Cache-Control": "no-store"}


async def _document_body(request: Request) -> tuple[dict[str, Any], JSONResponse | None]:
    try:
        body = await request.json()
    except ValueError:
        return {}, JSONResponse({"error": "the body must be JSON"}, status_code=400)
    if not isinstance(body, dict) or "document" not in body:
        return {}, JSONResponse({"error": 'send {"document": {...}}'}, status_code=400)
    return cast(dict[str, Any], body), None


def _view(request: Request) -> dict[str, Any]:
    project_dir = ui_context(request).project_dir
    path = project_dir / CONFIG_FILENAME
    source = path.read_text(encoding="utf-8") if path.is_file() else None
    document, problem = read_document(project_dir, source=source)
    check = check_config(project_dir, document, source=source) if document is not None else None
    return {
        "document": document,
        "problem": problem,
        "schema": config_schema(),
        "defaults": ProjectConfig.model_validate({"providers": {}}).model_dump(mode="json"),
        "check": check.to_json() if check is not None else None,
        "revision": revision_of(source) if source is not None else None,
        "config_hash": (
            config_hash(ProjectConfig.model_validate(check.effective))
            if check is not None and check.effective is not None
            else None
        ),
    }


async def config(request: Request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(_view, request), headers=NO_STORE)


@same_origin_only
async def validate(request: Request) -> JSONResponse:
    body, refused = await _document_body(request)
    if refused is not None:
        return refused
    check = await run_in_threadpool(check_config, ui_context(request).project_dir, body["document"])
    return JSONResponse(check.to_json(), headers=NO_STORE)


def _save(project_dir: Path, document: Any, expected: str | None) -> JSONResponse:
    path = project_dir / CONFIG_FILENAME
    lock_path = project_dir / "build" / "config.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(lock_path, timeout=5, fallback_to_soft=False, preserve_lock_file=True):
            source = path.read_text(encoding="utf-8")
            if expected is not None and revision_of(source) != expected:
                return JSONResponse(
                    {"error": "The project config changed on disk. Reload before saving again."},
                    status_code=409,
                    headers=NO_STORE,
                )
            check = check_config(project_dir, document, source=source)
            if not check.ok:
                return JSONResponse(check.to_json(), status_code=422, headers=NO_STORE)
            actual, problem = read_document(project_dir, source=check.yaml)
            if problem is not None or actual != document:
                return JSONResponse(
                    {"error": "The YAML preview could not preserve the edited settings."},
                    status_code=422,
                    headers=NO_STORE,
                )
            if source != check.yaml:
                write_atomically(path, check.yaml.encode("utf-8"))
    except (OSError, Timeout) as exc:
        return JSONResponse(
            {"error": f"Cannot save the project config: {exc}"}, status_code=500, headers=NO_STORE
        )
    current_hash = config_hash(ProjectConfig.model_validate(actual))
    run = read_run_state(project_dir)
    return JSONResponse(
        {
            **check.to_json(),
            "revision": revision_of(check.yaml),
            "config_hash": current_hash,
            "pending_change": bool(
                run is not None and run.status in ACTIVE and run.config_hash != current_hash
            ),
        },
        headers=NO_STORE,
    )


@same_origin_only
async def save(request: Request) -> JSONResponse:
    body, refused = await _document_body(request)
    if refused is not None:
        return refused
    expected = body.get("revision")
    if expected is not None and not isinstance(expected, str):
        return JSONResponse({"error": "revision must be a string"}, status_code=400)
    return await run_in_threadpool(
        _save, ui_context(request).project_dir, body["document"], expected
    )


def _plan(project_dir: Path, document: Any) -> JSONResponse:
    check = check_config(project_dir, document)
    if not check.ok:
        return JSONResponse(check.to_json(), status_code=422, headers=NO_STORE)
    try:
        proposed = plan(
            project_dir, config=ProjectConfig.model_validate(check.effective), estimate=True
        )
    except (OSError, ValueError) as exc:
        return JSONResponse(
            {"error": f"Cannot estimate regeneration: {exc}"},
            status_code=409,
            headers=NO_STORE,
        )
    report = proposed.report
    assert report is not None
    return JSONResponse(
        {
            "ok": proposed.ok,
            "problems": proposed.problems,
            "gates": proposed.gates,
            **report.model_dump(mode="json"),
        },
        headers=NO_STORE,
    )


@same_origin_only
async def plan_config(request: Request) -> JSONResponse:
    body, refused = await _document_body(request)
    if refused is not None:
        return refused
    return await run_in_threadpool(_plan, ui_context(request).project_dir, body["document"])


async def providers(request: Request) -> JSONResponse:
    choices = await run_in_threadpool(provider_choices, ui_context(request).project_dir)
    return JSONResponse(choices, headers=NO_STORE)


@same_origin_only
async def check_providers(request: Request) -> JSONResponse:
    body, refused = await _document_body(request)
    if refused is not None:
        return refused
    choices = await run_in_threadpool(
        provider_choices, ui_context(request).project_dir, body["document"]
    )
    return JSONResponse(choices, headers=NO_STORE)


def routes() -> list[Route]:
    return [
        Route("/api/config", config, methods=["GET"]),
        Route("/api/config/validate", validate, methods=["POST"]),
        Route("/api/config/save", save, methods=["POST"]),
        Route("/api/config/plan", plan_config, methods=["POST"]),
        Route("/api/providers", providers, methods=["GET"]),
        Route("/api/providers/check", check_providers, methods=["POST"]),
    ]
