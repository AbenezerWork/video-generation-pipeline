"""What a stage left in the project, as JSON-ready dicts for the stage detail (no web framework).

Everything is read from the project's ``build/`` and ``out/`` folders as they are now: the stage's
own JSON (script, storyboard, translation reviews, fit plan), the media indexes the stages write,
and the ledger (``build/ledger.json``) for timing and GPU time. A stage that has not run yet simply
has nothing to show. Media are referred to by a URL under ``/media/`` that
:mod:`vidpipe.ui.detail` serves.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError

from vidpipe.artifacts import LEDGER_FILENAME, ArtifactRecord, Ledger
from vidpipe.models import Brief, FitPlan, MediaIndex, Narration, Script, Storyboard
from vidpipe.project import Project, ProjectError
from vidpipe.stages import STAGE_NAMES
from vidpipe.translate import TranslationReview, review_path

#: Media types the UI serves, by file suffix: (kind, content type). Nothing else is served.
MEDIA_TYPES: dict[str, tuple[str, str]] = {
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"),
    ".mp4": ("video", "video/mp4"),
    ".webm": ("video", "video/webm"),
    # The fake video provider's raw frames: served (to download), but no browser plays them.
    ".y4m": ("video", "video/x-yuv4mpeg"),
    ".wav": ("audio", "audio/wav"),
    ".mp3": ("audio", "audio/mpeg"),
    ".flac": ("audio", "audio/flac"),
    ".ogg": ("audio", "audio/ogg"),
    ".srt": ("subtitles", "application/x-subrip"),
}

#: The project folders media may come from (relative to the project root).
MEDIA_ROOTS = ("build", "out")


class StageNotFound(LookupError):
    pass


def media_url(relative_to_root: str) -> str:
    """``build/keyframes/shot_01.png`` -> ``/media/build/keyframes/shot_01.png``."""
    return "/media/" + PurePosixPath(relative_to_root).as_posix()


def _media(project_root: Path, relative_to_root: str, **about: Any) -> dict[str, Any] | None:
    """One media file, or ``None`` when it is gone or of a type the UI does not serve."""
    path = project_root / relative_to_root
    known = MEDIA_TYPES.get(path.suffix.lower())
    if known is None or not path.is_file():
        return None
    kind, content_type = known
    return {
        "kind": kind,
        "content_type": content_type,
        "path": PurePosixPath(relative_to_root).as_posix(),
        "url": media_url(relative_to_root),
        "size": path.stat().st_size,
        **about,
    }


def _read[M: BaseModel](build: Path, relative: str, model: type[M]) -> M | None:
    try:
        return model.model_validate_json((build / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def read_ledger(project_root: Path) -> Ledger:
    ledger = _read(project_root / "build", LEDGER_FILENAME, Ledger)
    return ledger if ledger is not None else Ledger()


def stage_records(project_root: Path, stage: str) -> list[ArtifactRecord]:
    """The ledger's records for ``stage`` whose output files are all still there."""
    return [
        record
        for record in read_ledger(project_root).artifacts.values()
        if record.stage == stage and all((project_root / o.path).is_file() for o in record.outputs)
    ]


def ledger_records(project_dir: Path, stage: str) -> list[dict[str, Any]]:
    """The stage's ledger records in key order: what made each artifact, from what, at what cost.

    Provider options are left out (they come from the project config, shown in the Config view).
    """
    if stage not in STAGE_NAMES:
        raise StageNotFound(stage)
    records = sorted(stage_records(project_dir.resolve(), stage), key=lambda r: r.key)
    return [
        {
            "key": r.key,
            "provider": r.provider,
            "seed": r.seed,
            "parameters": r.parameters,
            "gpu_seconds": round(r.gpu_seconds, 3),
            "wall_seconds": round(r.wall_seconds, 3),
            "started_at": r.started_at,
            "fallback": r.fallback,
            "input_hash": r.input_hash,
            "outputs": [o.path for o in r.outputs],
        }
        for r in records
    ]


def _timing(records: list[ArtifactRecord]) -> dict[str, Any] | None:
    """What the ledger says the stage's current artifacts cost, each when it was last generated."""
    if not records:
        return None
    return {
        "artifacts": len(records),
        "wall_seconds": round(sum(r.wall_seconds for r in records), 3),
        "gpu_seconds": round(sum(r.gpu_seconds for r in records), 3),
        "first_started_at": min(r.started_at for r in records),
        "last_started_at": max(r.started_at for r in records),
        "fallbacks": [{"key": r.key, "note": r.fallback} for r in records if r.fallback],
    }


def _index_media(project_root: Path, name: str) -> list[dict[str, Any]]:
    index = _read(project_root / "build", name, MediaIndex)
    if index is None:
        return []
    found = (
        _media(
            project_root,
            f"build/{item.path}",
            shot_id=item.shot_id,
            visual_set=item.visual_set,
            clip=item.clip,
        )
        for item in index.items
    )
    return [m for m in found if m is not None]


def _scripts(build: Path, languages: list[str]) -> dict[str, Script]:
    """Each language's script: the source script, then each translation that exists."""
    scripts: dict[str, Script] = {}
    if (source := _read(build, "script.json", Script)) is not None:
        scripts[source.language] = source
    for lang in languages[1:]:
        if (translated := _read(build, f"translation/{lang}.json", Script)) is not None:
            scripts[lang] = translated
    return scripts


def _script_json(script: Script) -> dict[str, Any]:
    return {
        "language": script.language,
        "title": script.title,
        "lines": [{"id": line.id, "text": line.text} for line in script.lines],
    }


def _translations(
    build: Path, languages: list[str], *, from_contract: bool
) -> list[dict[str, Any]]:
    """Per target language: each line beside its source, with the back-translation check."""
    source = _read(build, "script.json", Script)
    if source is None:
        return []
    scripts = _scripts(build, languages)
    out: list[dict[str, Any]] = []
    for lang in languages[1:]:
        if (translated := scripts.get(lang)) is None:
            continue
        review = None if from_contract else _read(build, review_path(lang), TranslationReview)
        checks = {c.id: c for c in review.lines} if review else {}
        texts = {line.id: line.text for line in translated.lines}
        lines: list[dict[str, Any]] = []
        for line in source.lines:
            check = checks.get(line.id)
            lines.append(
                {
                    "id": line.id,
                    "source": line.text,
                    "translation": texts.get(line.id, ""),
                    "back_translation": check.back_translation if check else None,
                    "status": check.status if check else None,
                    "reason": check.reason if check else "",
                }
            )
        out.append(
            {
                "language": lang,
                "source_language": source.language,
                "reviewed": review is not None,
                "translator": review.translator if review else None,
                "checker": review.checker if review else None,
                "same_model": review.same_model if review else None,
                "drifted": sum(1 for line in lines if line["status"] == "drift"),
                "lines": lines,
            }
        )
    return out


def _storyboard(build: Path) -> dict[str, Any] | None:
    storyboard = _read(build, "storyboard.json", Storyboard)
    if storyboard is None:
        return None
    script = _read(build, "script.json", Script)
    lines = {line.id: line.text for line in script.lines} if script else {}
    return {
        "shots": [
            {
                "id": shot.id,
                "line_id": shot.line_id,
                "line": lines.get(shot.line_id, ""),
                "visual": shot.visual,
                "reason": shot.reason,
                "motion_type": shot.motion_type.value,
                "character": shot.character,
                "location": shot.location,
            }
            for shot in storyboard.shots
        ]
    }


def _narration(root: Path, languages: list[str]) -> list[dict[str, Any]]:
    """Each narration clip with the line it speaks, in its own language."""
    build = root / "build"
    narration = _read(build, "narration.json", Narration)
    if narration is None:
        return []
    storyboard = _read(build, "storyboard.json", Storyboard)
    line_of = {s.id: s.line_id for s in storyboard.shots} if storyboard else {}
    texts = {
        lang: {line.id: line.text for line in script.lines}
        for lang, script in _scripts(build, languages).items()
    }
    found = (
        _media(
            root,
            f"build/{clip.path}",
            shot_id=clip.shot_id,
            language=clip.language,
            duration_s=clip.duration_s,
            text=texts.get(clip.language, {}).get(line_of.get(clip.shot_id, -1), ""),
        )
        for clip in narration.clips
    )
    return [m for m in found if m is not None]


def _fit_plan(build: Path) -> dict[str, Any] | None:
    plan = _read(build, "fit_plan.json", FitPlan)
    if plan is None:
        return None
    return {
        "visuals": plan.visuals.value,
        "shots": len(plan.shots),
        "clip_count": plan.clip_count,
        "clip_seconds": round(plan.clip_seconds, 2),
        "continuation_clips": sum(s.continuation_clips for s in plan.shots),
        "render_seconds": {k: round(v, 2) for k, v in plan.render_seconds.items()},
        "music_seconds": plan.music_seconds,
        "limits": plan.limits.model_dump(),
        "problems": plan.problems,
    }


def _renders(
    root: Path, records: list[ArtifactRecord], languages: list[str]
) -> list[dict[str, Any]]:
    """Each language's final render and its subtitle file, in the project's language order."""
    by_language = {r.parameters.get("language"): r for r in records}
    media: list[dict[str, Any]] = []
    for lang in languages:
        record = by_language.get(lang)
        for output in record.outputs if record else []:
            if (item := _media(root, output.path, language=lang)) is not None:
                media.append(item)
    return media


def stage_outputs(project_dir: Path, stage: str) -> dict[str, Any]:
    """The stage detail: the stage's media and text outputs, and its timing from the ledger.

    Keys: ``stage``; ``timing`` (``None`` before the stage first ran); ``media`` (files, each with
    ``kind`` image/video/audio/subtitles, ``url``, ``content_type`` and, where it applies,
    ``shot_id``, ``language``, ``visual_set``, ``clip``, ``duration_s``, ``text``); and per stage
    ``brief``, ``script``, ``translations``, ``storyboard`` or ``fit_plan``.
    """
    if stage not in STAGE_NAMES:
        raise StageNotFound(stage)
    root = project_dir.resolve()
    build = root / "build"
    project = _project(root)
    languages = project.config.languages if project else []
    records = stage_records(root, stage)
    detail: dict[str, Any] = {"stage": stage, "timing": _timing(records), "media": []}
    if stage == "brief":
        brief = _read(build, "brief.json", Brief)
        detail["brief"] = brief.model_dump() if brief else None
    elif stage == "script":
        source = _read(build, "script.json", Script)
        detail["script"] = _script_json(source) if source else None
    elif stage == "translation":
        script_languages = project.config.script_languages if project else []
        detail["translations"] = _translations(
            build, script_languages, from_contract=(root / "storyboard.json").is_file()
        )
    elif stage == "storyboard":
        detail["storyboard"] = _storyboard(build)
    elif stage == "narration":
        detail["media"] = _narration(root, languages)
    elif stage == "fit-planning":
        detail["fit_plan"] = _fit_plan(build)
    elif stage in ("keyframes", "video", "music"):
        detail["media"] = _index_media(root, f"{stage}.json")
    elif stage == "assembly":
        detail["media"] = _renders(root, records, languages)
    return detail


def _project(project_dir: Path) -> Project | None:
    try:
        return Project(project_dir)
    except ProjectError:
        return None
