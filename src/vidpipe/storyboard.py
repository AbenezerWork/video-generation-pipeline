"""Schema generation and export of a project's editable storyboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from vidpipe.config import ProjectConfig
from vidpipe.fit_inputs import script_for
from vidpipe.lock import writer_lock
from vidpipe.models import ContractShot, Storyboard, StoryboardContract, StoryboardMusic
from vidpipe.project import Project, ProjectError
from vidpipe.runstate import write_atomically


def write_schemas(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, model in (("storyboard", StoryboardContract), ("vidpipe", ProjectConfig)):
        path = directory / f"{name}.schema.json"
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **model.model_json_schema(),
        }
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def default_music_prompt(title: str) -> str:
    return f"Instrumental score for: {title}"


def export_storyboard(root: Path) -> Path:
    with writer_lock(root):
        project = Project(root)
        path = project.root / "storyboard.json"
        if path.exists():
            raise ProjectError(f"{path} already exists")
        try:
            board = project.read_model("storyboard.json", Storyboard)
            lines: dict[str, dict[int, str]] = {}
            title = project.load_brief().title
            for language in project.config.languages:
                script = script_for(project, language)
                if script is None:
                    raise ValueError(f"missing built script for {language!r}")
                lines[language] = {line.id: line.text for line in script.lines}
                if language == project.config.primary_language:
                    title = script.title
            music = project.config.providers.get("music")

            options = music.options.get("settings") if music else None
            settings = cast(dict[str, Any], options) if isinstance(options, dict) else {}
            score = StoryboardMusic.model_validate(
                {
                    "prompt": default_music_prompt(project.load_brief().title),
                    **{
                        field: settings[field] for field in ("bpm", "keyscale") if field in settings
                    },
                }
            )
            contract = StoryboardContract(
                title=title,
                shots=[
                    ContractShot(
                        id=shot.id,
                        reason=shot.reason or f"Illustrates narration line {shot.line_id}.",
                        narration={lang: texts[shot.line_id] for lang, texts in lines.items()},
                        visual=shot.visual,
                        motion_type=shot.motion_type,
                        character=shot.character,
                        location=shot.location,
                    )
                    for shot in board.shots
                ],
                music=score,
            )
        except (OSError, ValueError, KeyError) as exc:
            raise ProjectError(f"cannot export storyboard from {project.build}: {exc}") from exc
        write_atomically(path, (contract.model_dump_json(indent=2) + "\n").encode("utf-8"))
        return path
