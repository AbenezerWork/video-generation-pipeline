"""The dry run behind ``vidpipe plan``: what a run would do and cost, without generating anything.

Built only from what is already on disk and from the providers' declarations:

* the fit plan (segments, speed factors, continuation clips) for the storyboard's shots, using the
  real narration durations recorded in the ledger where narration was generated for the current
  text, and an estimate from the script text (at the TTS provider's declared speaking rate)
  everywhere else;
* the cost of every stage from its provider's declared :class:`~vidpipe.contracts.CostModel`,
  as GPU minutes (local) or dollars (hosted). Estimates are for a run from scratch: unchanged
  artifacts are skipped at run time and cost nothing then.

Nothing here calls a provider's generation method or writes to the project.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from vidpipe.artifacts import ArtifactStore, digest
from vidpipe.chain import describe
from vidpipe.config import STAGE_KINDS
from vidpipe.contracts import ImageToVideoProvider, Provider, TTSProvider
from vidpipe.fit import NarrationInput, ShotInput, limits_for, plan_fit
from vidpipe.fit_inputs import Narrate, collect_shots, script_for
from vidpipe.models import CONTRACT_STAGES, FitPlan, Storyboard
from vidpipe.project import Project


class StageEstimate(BaseModel):
    stage: str
    provider: str | None
    #: ``None`` when the estimate cannot be made yet (it needs the storyboard's shot count).
    gpu_minutes: float | None = None
    dollars: float | None = None
    calls: int | None = None
    output_seconds: float | None = None
    detail: str = ""


class StageRegeneration(BaseModel):
    stage: str
    #: Estimated number that could regenerate, or None if earlier outputs are needed.
    artifacts: int | None
    gpu_minutes: float | None
    #: True if this stage may reuse everything once its upstream outputs are known.
    possible: bool


class RegenerationReport(BaseModel):
    stages: list[StageRegeneration]
    gpu_minutes: float
    complete: bool


class PlanReport(BaseModel):
    stages: list[StageEstimate]
    #: Totals over the stages that could be estimated.
    gpu_minutes: float
    dollars: float
    #: Whether every stage could be estimated (otherwise the totals are a lower bound).
    complete: bool
    regeneration: RegenerationReport | None = None
    fit: FitPlan | None = None
    notes: list[str] = Field(default_factory=list[str])


def _narrator(project: Project, providers: Mapping[str, Provider[Any]]) -> Narrate:
    """Each shot's narration: the real, recorded one if it is current, otherwise an estimate."""
    store = ArtifactStore(project)
    tts = providers.get("narration")
    selected = project.config.providers.get("narration")
    per_char = tts.capabilities.seconds_per_char if isinstance(tts, TTSProvider) else 0.08

    def narrate(language: str, shot_id: int, text: str) -> NarrationInput:
        # Real only if the ledger holds narration of exactly this text from the selected provider.
        record = store.record(f"narration/{language}/shot_{shot_id:02d}")
        if (
            record is not None
            and selected is not None
            and record.provider == selected.name
            and record.inputs.get("value:text") == digest(text)
            and "duration_s" in record.data
        ):
            return NarrationInput(text, float(record.data["duration_s"]))
        return NarrationInput(text, len(text.strip()) * per_char, estimated=True)

    return narrate


def build_report(
    project: Project, providers: Mapping[str, Provider[Any]], stages: list[str]
) -> PlanReport:
    """The plan and estimates for ``stages`` (in order) of ``project``."""
    config = project.config
    notes: list[str] = []
    video = providers.get("video")

    storyboard: Storyboard | None = None
    if contract := project.storyboard_contract:
        storyboard = contract.storyboard()
    elif (project.build / "storyboard.json").is_file() and script_for(
        project, config.primary_language
    ):
        storyboard = project.read_model("storyboard.json", Storyboard)
    else:
        notes.append(
            "no storyboard yet, so shot counts, clip plans and the estimates that depend on them "
            f"are unknown: run `vidpipe run {project.root} --until storyboard` first"
        )
    shots = collect_shots(project, storyboard, _narrator(project, providers)) if storyboard else []

    fit: FitPlan | None = None
    if shots and isinstance(video, ImageToVideoProvider) and "fit-planning" in stages:
        fit = plan_fit(
            shots,
            languages=config.languages,
            primary_language=config.primary_language,
            visuals=config.visuals,
            limits=limits_for(video.capabilities),
        )
    narrations = [n for s in shots for n in s.narration.values()]
    guessed = sum(n.estimated for n in narrations)
    if guessed:
        notes.append(
            f"narration durations are estimated from the script text for {guessed} of "
            f"{len(narrations)} narration clips (the TTS provider's declared speaking rate)"
        )

    estimates = [_estimate(name, project, providers, shots, fit) for name in stages]
    known = [e for e in estimates if e.gpu_minutes is not None]
    return PlanReport(
        stages=estimates,
        gpu_minutes=sum(e.gpu_minutes or 0.0 for e in known),
        dollars=sum(e.dollars or 0.0 for e in known),
        complete=all(
            e.gpu_minutes is not None or config.providers.get(e.stage) is None for e in estimates
        ),
        fit=fit,
        notes=notes,
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _estimate(
    stage: str,
    project: Project,
    providers: Mapping[str, Provider[Any]],
    shots: list[ShotInput],
    fit: FitPlan | None,
) -> StageEstimate:
    """What one stage would cost: ``gpu_minutes`` is ``None`` until what it needs is known."""
    config = project.config
    selection = config.providers.get(stage)
    provider = providers.get(stage)
    kind = STAGE_KINDS.get(stage)
    label = describe(kind, selection) if kind is not None and selection is not None else None
    estimate = StageEstimate(stage=stage, provider=label)
    if project.storyboard_contract and stage in CONTRACT_STAGES:
        return StageEstimate(stage=stage, provider=None, gpu_minutes=0.0, dollars=0.0, calls=0)
    if selection is None:  # brief, fit-planning, assembly: no provider, no GPU
        return estimate.model_copy(update={"gpu_minutes": 0.0, "dollars": 0.0})
    if provider is None:
        return estimate  # unknown provider: already reported as a plan problem

    seconds = 0.0
    if stage in ("script", "storyboard"):
        calls, detail = 1, "1 call"
    elif stage == "translation":
        calls = len(config.languages) - 1
        detail = _plural(calls, "language")
    elif not shots:
        return estimate  # everything below needs the storyboard's shots
    elif stage == "narration":
        calls = len(shots) * len(config.languages)
        seconds = sum(n.duration_s for s in shots for n in s.narration.values())
        detail = f"{_plural(calls, 'clip')}, {seconds:.1f} s of speech"
    elif stage == "keyframes":
        calls = len(shots)
        detail = _plural(calls, "image")
    elif stage == "video" and fit is not None:
        calls, seconds = fit.clip_count, fit.clip_seconds
        detail = f"{_plural(calls, 'clip')}, {seconds:g} s of video"
    elif stage == "music" and fit is not None:
        calls, seconds = 1, float(fit.music_seconds)
        detail = f"{seconds:g} s of music"
    else:
        return estimate
    cost = provider.cost.estimate(calls=calls, output_seconds=seconds)
    return estimate.model_copy(
        update={
            "gpu_minutes": cost.gpu_minutes,
            "dollars": cost.dollars,
            "calls": calls,
            "output_seconds": seconds or None,
            "detail": detail,
        }
    )


# ------------------------------------------------------------------------------------- text


def _cost_text(estimate: StageEstimate) -> str:
    if estimate.gpu_minutes is None or estimate.dollars is None:
        return "?"
    parts: list[str] = []
    if estimate.gpu_minutes:
        parts.append(f"{estimate.gpu_minutes:.2f} gpu-min")
    if estimate.dollars:
        parts.append(f"${estimate.dollars:.2f}")
    text = ", ".join(parts) or "-"
    return f"{text} ({estimate.detail})" if estimate.detail else text


def _quote(text: str, width: int = 72) -> str:
    return f'"{text if len(text) <= width else text[: width - 1] + "…"}"'


def format_fit(fit: FitPlan) -> list[str]:
    """The fit plan as lines: clips per shot, then each language's speed and narration segments."""
    lines = [f"fit plan (visuals: {fit.visuals.value})"]
    for shot in fit.shots:
        lines.append(f"shot {shot.shot_id}")
        for visual_set in shot.visual_sets.values():
            n = len(visual_set.clips)
            sizes = ", ".join(
                f"{c.seconds:g}s" + (" continuation" if c.continues is not None else "")
                for c in visual_set.clips
            )
            lines.append(f"  clips [{visual_set.id}] {n} clip{'s' if n != 1 else ''}: {sizes}")
        for language in shot.languages.values():
            kind = "estimated" if language.estimated else "narration"
            lines.append(f"  {language.language}  {language.seconds:.2f}s {kind}")
            for segment in language.segments:
                speed = next((c.speed for c in language.clips if c.clip == segment.clip), 1.0)
                lines.append(
                    f"      {segment.start_s:.2f}-{segment.end_s:.2f}s  clip {segment.clip + 1}  "
                    f"speed {speed:.2f}x  {_quote(segment.text)}"
                )
    renders = ", ".join(f"{lang} {s:.1f}s" for lang, s in fit.render_seconds.items())
    lines.append(f"renders: {renders} (limit {fit.limits.max_render_s:g}s)")
    return lines


def format_report(report: PlanReport) -> str:
    """The text ``vidpipe plan`` prints: one line per stage with its estimate, then the fit plan."""
    lines = [f"{e.stage:<14}{e.provider or '-':<20}{_cost_text(e)}" for e in report.stages]
    total = f"{report.gpu_minutes:.2f} gpu-min, ${report.dollars:.2f}"
    partial = "" if report.complete else " (so far; more is unknown)"
    lines.append(f"estimated total: {total}{partial}")
    if report.regeneration is not None:
        impact = report.regeneration
        lines += ["", "estimated work with the current ledger:"]
        if not impact.stages:
            lines.append("  all artifacts can be reused")
        for stage in impact.stages:
            count = (
                "unknown artifact count"
                if stage.artifacts is None
                else (f"up to {_plural(stage.artifacts, 'artifact')}")
            )
            gpu = (
                "unknown GPU time"
                if stage.gpu_minutes is None
                else (f"{stage.gpu_minutes:.2f} gpu-min")
            )
            action = "may regenerate" if stage.possible else "regenerates"
            lines.append(f"  {stage.stage}: {action}, {count}, {gpu}")
        suffix = "" if impact.complete else " (known estimates only)"
        lines.append(f"  estimated GPU time: {impact.gpu_minutes:.2f} gpu-min{suffix}")
    if report.fit is not None:
        lines += ["", *format_fit(report.fit)]
    lines += ["", *(f"note: {note}" for note in report.notes)] if report.notes else []
    return "\n".join(lines)
