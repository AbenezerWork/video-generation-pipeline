"""Gathering what the fit planner needs from a project: each shot's narration text and duration."""

from __future__ import annotations

from collections.abc import Callable

from vidpipe.fit import NarrationInput, ShotInput
from vidpipe.models import Script, Storyboard
from vidpipe.project import Project

#: (language, shot id, text) -> the narration to plan with (real or estimated duration).
Narrate = Callable[[str, int, str], NarrationInput]


def translation_files(project: Project) -> list[str]:
    """The script files (relative to ``build/``) that every shot's narration text comes from."""
    return ["script.json", *(f"translation/{lang}.json" for lang in project.config.languages[1:])]


def script_for(project: Project, language: str) -> Script | None:
    """A language's script, or ``None`` while it has not been written or translated yet."""
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
    return [
        ShotInput(
            shot_id=shot.id,
            narration={
                language: narrate(language, shot.id, texts[language][shot.line_id])
                for language in project.config.languages
            },
        )
        for shot in storyboard.shots
    ]
