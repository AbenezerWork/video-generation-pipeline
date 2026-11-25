"""The token required when the UI listens beyond this machine (``vidpipe ui --host``).

``vidpipe ui`` prints a link carrying the token: ``http://<host>:<port>/?token=<token>``. Opening
it answers with a redirect to the same address without the token, setting the token as an
``HttpOnly`` cookie, so the token leaves the address bar and history, and the page, its assets,
``fetch`` calls and the ``EventSource`` stream all carry it from then on (same origin). Scripts can
send ``Authorization: Bearer <token>`` instead. Anything else gets ``401``.

The cookie is ``SameSite=Lax``: sent when the link is opened from another app, never on another
site's POSTs (the actions later tickets add).
"""

from __future__ import annotations

import secrets

from starlette.datastructures import URL
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE = "vidpipe_token"
QUERY = "token"


def new_token() -> str:
    """A fresh random token (256 bits), printed by ``vidpipe ui`` at startup."""
    return secrets.token_urlsafe(32)


class TokenGate:
    """ASGI middleware letting through only requests that carry ``token``."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    def _matches(self, candidate: str | None) -> bool:
        return candidate is not None and secrets.compare_digest(
            candidate.encode("utf-8"), self.token.encode("utf-8")
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        response: Response | None = None
        offered = connection.query_params.get(QUERY)
        if offered is not None and scope.get("method") == "GET" and self._matches(offered):
            response = RedirectResponse(_without_token(connection.url), status_code=303)
            response.set_cookie(COOKIE, self.token, httponly=True, samesite="lax", path="/")
            response.headers["Referrer-Policy"] = "no-referrer"
        elif self._matches(connection.cookies.get(COOKIE)) or self._matches(_bearer(connection)):
            await self.app(scope, receive, send)
            return
        else:
            message = "this vidpipe UI needs its token: open the link vidpipe ui printed"
            if connection.url.path.startswith("/api/"):
                response = JSONResponse({"error": message}, status_code=401)
            else:
                response = PlainTextResponse(message, status_code=401)
        await response(scope, receive, send)


def _bearer(connection: HTTPConnection) -> str | None:
    scheme, _, value = connection.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else None


def _without_token(url: URL) -> str:
    rest = url.remove_query_params(QUERY)
    return rest.path + (f"?{rest.query}" if rest.query else "")
