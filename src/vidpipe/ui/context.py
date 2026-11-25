"""What every route of one UI server shares: the project it serves and its settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from starlette.requests import HTTPConnection


@dataclass(frozen=True)
class UiContext:
    project_dir: Path
    #: How often the event stream looks at the run state, in seconds.
    poll_interval: float = 0.25


def ui_context(connection: HTTPConnection) -> UiContext:
    context: UiContext = connection.app.state.ui
    return context
