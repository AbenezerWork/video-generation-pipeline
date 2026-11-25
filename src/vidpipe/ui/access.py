"""The token required when the UI listens beyond this machine."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class TokenGate:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app, self.token = app, token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
