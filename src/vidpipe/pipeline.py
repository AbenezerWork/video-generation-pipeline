"""Library entry points: :func:`plan` and :func:`run` over a project directory."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vidpipe.assembly import Assembler, FfmpegAssembler
from vidpipe.config import STAGE_KINDS
from vidpipe.contracts import Provider
from vidpipe.estimate import PlanReport, build_report
from vidpipe.models import Manifest, StageRecord
from vidpipe.project import Project
from vidpipe.registry import Registry, UnknownProvider, default_registry
from vidpipe.stages import STAGE_NAMES, STAGES, StageContext, StageError


class PlanError(Exception):
    """The plan has problems; nothing was generated."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class PlannedStage:
    name: str
    provider: str | None


@dataclass
class Plan:
    stages: list[PlannedStage]
    problems: list[str] = field(default_factory=list[str])
    #: Fit plan and cost estimates (only when asked for: ``plan(..., estimate=True)``).
    report: PlanReport | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class RunResult:
    plan: Plan
    manifest: Manifest


def _selected_stages(until: str | None) -> list[str]:
    if until is None:
        return list(STAGE_NAMES)
    if until not in STAGE_NAMES:
        raise PlanError([f"unknown stage {until!r} (stages: {', '.join(STAGE_NAMES)})"])
    return STAGE_NAMES[: STAGE_NAMES.index(until) + 1]


def _build_context(
    project: Project, registry: Registry, assembler: Assembler, problems: list[str]
) -> StageContext:
    providers: dict[str, Provider[Any]] = {}
    for stage, selection in project.config.providers.items():
        kind = STAGE_KINDS.get(stage)
        if kind is None:
            continue  # e.g. `song`: configurable, but not part of the stage graph yet
        try:
            providers[stage] = registry.create(kind, selection.name, **selection.options)
        except UnknownProvider as exc:
            problems.append(f"{stage}: {exc}")
        except (TypeError, ValidationError) as exc:
            problems.append(f"{stage}: cannot configure provider {selection.name!r}: {exc}")
    return StageContext(project=project, providers=providers, assembler=assembler)


def plan(
    project_dir: Path,
    *,
    until: str | None = None,
    registry: Registry | None = None,
    assembler: Assembler | None = None,
    estimate: bool = False,
) -> Plan:
    """Resolve providers and check capabilities for every stage up to ``until``.

    Nothing is generated. Problems are collected rather than raised, so ``vidpipe plan`` can
    report them all. With ``estimate`` the plan also carries the fit plan (segments, speed
    factors, continuation clips) and the estimated GPU time and cost per stage, built from what is
    on disk; fit problems (a render over 90 s, narration no clip can cover) are added to
    ``problems``.
    """
    project = Project(project_dir)
    names = _selected_stages(until)
    problems: list[str] = []
    ctx = _build_context(
        project, registry or default_registry(), assembler or FfmpegAssembler(), problems
    )
    planned: list[PlannedStage] = []
    for stage in STAGES:
        if stage.name not in names:
            continue
        selection = project.config.providers.get(stage.name)
        planned.append(PlannedStage(stage.name, selection.name if selection else None))
        if stage.name in STAGE_KINDS and stage.name not in ctx.providers:
            if selection is None:
                problems.append(f"{stage.name}: no provider configured")
            continue
        try:
            problems += [f"{stage.name}: {p}" for p in stage.problems(ctx)]
        except StageError as exc:
            problems.append(f"{stage.name}: {exc}")
    report = None
    if estimate:
        report = build_report(project, ctx.providers, [p.name for p in planned])
        if report.fit is not None:
            problems += [f"fit-planning: {p}" for p in report.fit.problems]
    return Plan(stages=planned, problems=problems, report=report)


def run(
    project_dir: Path,
    *,
    until: str | None = None,
    registry: Registry | None = None,
    assembler: Assembler | None = None,
) -> RunResult:
    """Run the stage graph (up to ``until``). Capability problems abort before any generation."""
    the_plan = plan(project_dir, until=until, registry=registry, assembler=assembler)
    if not the_plan.ok:
        raise PlanError(the_plan.problems)

    project = Project(project_dir)
    problems: list[str] = []
    ctx = _build_context(
        project, registry or default_registry(), assembler or FfmpegAssembler(), problems
    )
    manifest = Manifest()
    wanted = set(_selected_stages(until))
    for stage in STAGES:
        if stage.name not in wanted:
            continue
        ctx.begin(stage.name)
        outputs = stage.run(ctx)
        selection = project.config.providers.get(stage.name)
        manifest.stages.append(
            StageRecord(
                stage=stage.name,
                provider=selection.name if selection else None,
                outputs=outputs,
                generated=ctx.generated,
                reused=ctx.reused,
            )
        )
        project.write_model("manifest.json", manifest)
    return RunResult(plan=the_plan, manifest=manifest)
