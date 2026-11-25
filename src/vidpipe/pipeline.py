"""Library entry points: :func:`plan` and :func:`run` over a project directory."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vidpipe.artifacts import ArtifactStore
from vidpipe.assembly import Assembler, FfmpegAssembler
from vidpipe.config import STAGE_KINDS
from vidpipe.contracts import Provider
from vidpipe.gates import Approver, GateError, GateKeeper
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
    #: Stages the run will pause after for approval (`gates:` in the config).
    gates: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class RunResult:
    plan: Plan
    manifest: Manifest
    #: The gate the run stopped at, waiting for approval; `None` when it ran to the end.
    paused_at: str | None = None


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
) -> Plan:
    """Resolve providers and check capabilities for every stage up to ``until``.

    Nothing is generated. Problems are collected rather than raised, so ``vidpipe plan`` can
    report them all.
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
    problems += [
        f"gates: unknown stage {gate!r} (stages: {', '.join(STAGE_NAMES)})"
        for gate in project.config.gates
        if gate not in STAGE_NAMES
    ]
    return Plan(stages=planned, problems=problems, gates=list(project.config.gates))


def run(
    project_dir: Path,
    *,
    until: str | None = None,
    registry: Registry | None = None,
    assembler: Assembler | None = None,
    auto: bool = False,
    approve: Sequence[str] = (),
    approver: Approver | None = None,
) -> RunResult:
    """Run the stage graph (up to ``until``). Capability problems abort before any generation.

    After a stage named in the config's ``gates`` the run stops (``RunResult.paused_at``) unless
    that gate is approved (``vidpipe.gates``): ``approve`` approves gates in advance, ``approver``
    is asked about the others, and ``auto`` skips every gate. A gate after the last stage the run
    was asked for holds nothing back, so it does not pause.
    """
    the_plan = plan(project_dir, until=until, registry=registry, assembler=assembler)
    problems = [f"--approve: unknown stage {g!r}" for g in approve if g not in STAGE_NAMES]
    if not the_plan.ok or problems:
        raise PlanError([*the_plan.problems, *problems])

    project = Project(project_dir)
    ctx = _build_context(
        project, registry or default_registry(), assembler or FfmpegAssembler(), []
    )
    keeper = GateKeeper(project, ctx.store)
    manifest = Manifest()
    paused_at: str | None = None
    wanted = set(_selected_stages(until))
    selected = [s for s in STAGES if s.name in wanted]
    for index, stage_obj in enumerate(selected):
        stage = stage_obj.name
        ctx.begin(stage)
        outputs = stage_obj.run(ctx)
        selection = project.config.providers.get(stage)
        manifest.stages.append(
            StageRecord(
                stage=stage,
                provider=selection.name if selection else None,
                outputs=outputs,
                generated=ctx.generated,
                reused=ctx.reused,
            )
        )
        project.write_model("manifest.json", manifest)
        if auto or stage not in project.config.gates or index == len(selected) - 1:
            continue
        if stage in approve:
            keeper.approve(stage)
        if not keeper.passes(stage, approver):
            paused_at = stage
            break
    return RunResult(plan=the_plan, manifest=manifest, paused_at=paused_at)


def approve(project_dir: Path, gates: Sequence[str]) -> None:
    """Approve what each gated stage has produced so far (``vidpipe approve``)."""
    project = Project(project_dir)
    keeper = GateKeeper(project, ArtifactStore(project))
    for gate in gates:
        if gate not in STAGE_NAMES:
            raise GateError(f"unknown stage {gate!r} (stages: {', '.join(STAGE_NAMES)})")
        keeper.approve(gate)
