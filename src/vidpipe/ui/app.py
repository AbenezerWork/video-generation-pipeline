"""The Starlette app behind ``vidpipe ui``: one project, its pages, JSON API and event stream.

Route conventions (later features add a module with a ``routes()`` list and one line below):

- ``/``: the console page (Run view; the Config view will be a second view of the same page).
- ``/static/...``: the no-build front end in ``vidpipe/ui/static``.
- ``GET /api/<thing>``: JSON reads (``project``, ``run``; later ``config``, ``providers``,
  ``stages/<stage>/outputs``, ``logs``). Media files go under ``/media/...``.
- ``POST /api/<thing>/<action>``: actions (later ``run/start``, ``run/stop``, ``run/stop-now``,
  ``gates/<stage>/approve``, ``shots/<n>/redo``, ``config/save``), answered with JSON.
- ``GET /api/events``: the one SSE stream; event ``run`` carries the run state (later ``config``).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import BaseRoute

from vidpipe.ui import api, config_api, events, pages
from vidpipe.ui.access import TokenGate
from vidpipe.ui.context import UiContext


def create_app(
    project_dir: Path,
    *,
    token: str | None = None,
    allowed_hosts: Sequence[str] | None = None,
    poll_interval: float = 0.25,
) -> Starlette:
    """The UI for ``project_dir``.

    ``token``: when set, every request must carry it (see :mod:`vidpipe.ui.access`); ``vidpipe ui``
    sets one whenever it listens beyond this machine. ``allowed_hosts``: the ``Host`` headers
    accepted (``vidpipe ui`` passes the loopback names when bound locally, so a web page cannot
    reach the UI by rebinding its own domain name to 127.0.0.1).
    """
    routes: list[BaseRoute] = [
        *pages.routes(),
        *api.routes(),
        *events.routes(),
        *config_api.routes(),
    ]
    middleware: list[Middleware] = []
    if allowed_hosts is not None:
        middleware.append(Middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts)))
    if token is not None:
        middleware.append(Middleware(TokenGate, token=token))
    app = Starlette(routes=routes, middleware=middleware)
    app.state.ui = UiContext(project_dir=project_dir.resolve(), poll_interval=poll_interval)
    return app
