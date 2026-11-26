"""Gathering what the fit planner needs from a project: each shot's narration text and duration."""

from __future__ import annotations

from collections.abc import Callable

from vidpipe.fit import NarrationInput, ShotInput
from vidpipe.models import Script, Storyboard
from vidpipe.project import Project, ProjectError

#: (language, shot id, text) -> the narration to plan with (real or estimated duration).
Narrate = Callable[[str, int, str], NarrationInput]


def script_for(project: Project, language: str) -> Script | None:
    """A language's script, or ``None`` while it has not been written or translated yet."""
    if contract := project.storyboard_contract:
        return contract.script(language)
    name = (
        "script.json"
        if language == project.config.primary_language
        else f"translation/{language}.json"
    )
    return project.read_model(name, Script) if (project.build / name).is_file() else None


def collect_shots(project: Project, storyboard: Storyboard, narrate: Narrate) -> list[ShotInput]:
    """One :class:`ShotInput` per storyboard shot. A language without a script of its own (not
    translated yet) borrows the primary language's text."""
    primary = script_for(project, project.config.primary_language)
    assert primary is not None
    texts: dict[str, dict[int, str]] = {}
    for language in project.config.languages:
        script = script_for(project, language) or primary
        texts[language] = {line.id: line.text for line in script.lines}
    shots: list[ShotInput] = []
    for shot in storyboard.shots:
        missing = [lang for lang in project.config.languages if shot.line_id not in texts[lang]]
        if missing:
            raise ProjectError(
                f"the storyboard's shot {shot.id} narrates script line {shot.line_id}, which "
                f"{', '.join(missing)} no longer has: rerun the storyboard after editing the script"
            )
        shots.append(
            ShotInput(
                shot_id=shot.id,
                narration={
                    language: narrate(language, shot.id, texts[language][shot.line_id])
                    for language in project.config.languages
                },
            )
        )
    return shots
