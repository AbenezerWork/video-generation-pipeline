"""``GET /api/events``: the one SSE stream a page listens to.

Event ``run``: the run state (README, "Run state") as JSON, or ``null`` before the project's first
run. One is sent on connect and then whenever the record changes: a new ``seq`` or ``run_id``, or a
status that :func:`~vidpipe.runstate.read_run_state` worked out (a run whose process died reads as
``failed`` without the file changing). The event ``id`` is ``<run_id>:<seq>``. A comment line keeps
idle connections open through proxies. Later the stream also carries ``config`` events.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Hashable
from pathlib import Path
from typing import Any

import anyio
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import BaseRoute, Route

from vidpipe.runstate import RunState, read_run_state
from vidpipe.ui.context import ui_context
from vidpipe.ui.summary import run_state_json

#: An idle stream sends a comment this often (seconds).
KEEPALIVE_S = 15.0
#: How long the browser waits before reconnecting a dropped stream (milliseconds).
RETRY_MS = 2000


def format_event(event: str, data: Any, event_id: str | None = None) -> str:
    lines = [f"event: {event}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def _run_key(state: RunState | None) -> Hashable:
    return None if state is None else (state.run_id, state.seq, state.status)


async def _stream(project_dir: Path, poll_interval: float) -> AsyncIterator[str]:
    yield f"retry: {RETRY_MS}\n\n"
    last: Hashable = object()
    quiet_since = time.monotonic()
    while True:
        state = await run_in_threadpool(read_run_state, project_dir)
        key = _run_key(state)
        if key != last:
            last = key
            event_id = None if state is None else f"{state.run_id}:{state.seq}"
            yield format_event("run", run_state_json(state), event_id)
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= KEEPALIVE_S:
            yield ": keepalive\n\n"
            quiet_since = time.monotonic()
        await anyio.sleep(poll_interval)


async def stream(request: Request) -> StreamingResponse:
    context = ui_context(request)
    return StreamingResponse(
        _stream(context.project_dir, context.poll_interval),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def routes() -> list[BaseRoute]:
    return [Route("/api/events", stream, methods=["GET"])]
