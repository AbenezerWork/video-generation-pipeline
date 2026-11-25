"""What the UI shows about a project, as JSON-ready dicts (no web framework in here).

The project summary is read fresh on every request: the project config can change on disk at any
time (by hand now, from the Config view later), and the run state belongs to the runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vidpipe.pipeline import provider_label
from vidpipe.project import Project, ProjectError
from vidpipe.runstate import ACTIVE, RunState, config_hash, read_run_state
from vidpipe.stages import STAGE_NAMES

#: The phase each stage belongs to; its signal hue on the rail (``data-phase``).
PHASES: dict[str, str] = {
    "brief": "words",
    "script": "words",
    "translation": "words",
    "storyboard": "words",
    "narration": "voice",
    "fit-planning": "voice",
    "keyframes": "picture",
    "video": "picture",
    "music": "sound",
    "assembly": "sound",
}


def stage_label(stage: str) -> str:
    """``fit-planning`` -> ``Fit planning``: how the interface names a stage."""
    return stage.replace("-", " ").capitalize()


def run_state_json(state: RunState | None) -> dict[str, Any] | None:
    return None if state is None else state.model_dump(mode="json")


def project_summary(project_dir: Path) -> dict[str, Any]:
    """The project as the Run view needs it: its stages (with provider and phase), the project
    config's gates and languages, and the current run state.

    An invalid project config does not fail the summary: ``problem`` says what is wrong and the
    stages are listed without providers.
    """
    state = read_run_state(project_dir)
    try:
        config = Project(project_dir).config
    except ProjectError as exc:
        config, problem = None, str(exc)
    else:
        problem = None
    current_hash = config_hash(config) if config is not None else None
    providers = config.providers if config is not None else {}
    gates = config.gates if config is not None else []
    return {
        "name": project_dir.resolve().name,
        "path": str(project_dir.resolve()),
        "languages": config.languages if config is not None else [],
        "gates": gates,
        "config_hash": current_hash,
        # ADR 0002: a config edited during a run applies to the next run.
        "pending_change": bool(
            state is not None and state.status in ACTIVE and state.config_hash != current_hash
        ),
        "problem": problem,
        "stages": [
            {
                "stage": name,
                "label": stage_label(name),
                "phase": PHASES[name],
                "provider": provider_label(name, providers.get(name)),
                "gate": name in gates,
            }
            for name in STAGE_NAMES
        ],
        "run": run_state_json(state),
    }
