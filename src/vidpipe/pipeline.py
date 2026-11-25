"""Library entry points: :func:`plan` and :func:`run` over a project directory."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vidpipe.artifacts import ArtifactStore
from vidpipe.assembly import Assembler, FfmpegAssembler
from vidpipe.chain import build_provider, describe
from vidpipe.config import STAGE_KINDS, ProviderSelection
from vidpipe.contracts import Cancelled, MusicProvider, ProjectContext, Provider
from vidpipe.estimate import PlanReport, build_report
from vidpipe.gates import Approver, GateError, GateKeeper, require_paused_gate
from vidpipe.lock import writer_lock
from vidpipe.models import Manifest, StageRecord, Storyboard
from vidpipe.project import Project
from vidpipe.registry import Registry, UnknownProvider, default_registry
from vidpipe.runstate import Origin, RunStatePublisher, resolve_origin
from vidpipe.stages import STAGE_NAMES, STAGES, Stage, StageContext, StageError
from vidpipe.stop import RunStopped, StopWatcher


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
    #: The run ended early because a stop was asked for (``vidpipe.stop``).
    stopped: bool = False


def provider_label(stage: str, selection: ProviderSelection | None) -> str | None:
    """The provider a stage uses, as ``plan``, the manifest and the run state name it (``None``
    for stages without a provider)."""
    kind = STAGE_KINDS.get(stage)
    return describe(kind, selection) if kind is not None and selection is not None else None


def _selected_stages(until: str | None) -> list[str]:
    if until is None:
        return list(STAGE_NAMES)
    if until not in STAGE_NAMES:
        raise PlanError([f"unknown stage {until!r} (stages: {', '.join(STAGE_NAMES)})"])
    return STAGE_NAMES[: STAGE_NAMES.index(until) + 1]


def _build_context(
    project: Project,
    registry: Registry,
    assembler: Assembler,
    problems: list[str],
    stop_now: Callable[[], bool] | None = None,
) -> StageContext:
    providers: dict[str, Provider[Any]] = {}
    about = ProjectContext(
        root=project.root, comfyui_url=project.config.comfyui.url, stop_now=stop_now
    )
    for stage, selection in project.config.providers.items():
        kind = STAGE_KINDS.get(stage)
        if kind is None:
            continue  # e.g. `song`: configurable, but not part of the stage graph yet
        try:
            provider = build_provider(registry, kind, selection)
            provider.attach(about)
            providers[stage] = provider
        except UnknownProvider as exc:
            problems.append(f"{stage}: {exc}")
        except (TypeError, ValueError) as exc:  # ValueError includes pydantic.ValidationError
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
        planned.append(PlannedStage(stage.name, provider_label(stage.name, selection)))
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
    report = None
    if estimate:
        report = build_report(project, ctx.providers, [p.name for p in planned])
        if report.fit is not None:
            problems += [f"fit-planning: {p}" for p in report.fit.problems]
            music = ctx.providers.get("music")
            if (
                "music" in names
                and isinstance(music, MusicProvider)
                and (problem := music.capabilities.duration_problem(report.fit.music_seconds))
            ):
                problems.append(f"music: {problem}")
    return Plan(stages=planned, problems=problems, gates=list(project.config.gates), report=report)


def run(
    project_dir: Path,
    *,
    until: str | None = None,
    registry: Registry | None = None,
    assembler: Assembler | None = None,
    auto: bool = False,
    approve: Sequence[str] = (),
    approver: Approver | None = None,
    origin: Origin | str | None = None,
    resume_gate: tuple[str, str] | None = None,
) -> RunResult:
    """Run the stage graph (up to ``until``). Capability problems abort before any generation.

    After a stage named in the config's ``gates`` the run stops (``RunResult.paused_at``) unless
    that gate is approved (``vidpipe.gates``): ``approve`` approves gates in advance, ``approver``
    is asked about the others, and ``auto`` skips every gate. A gate after the last stage the run
    was asked for holds nothing back, so it does not pause.

    The run holds the project's one-writer lock throughout (``vidpipe.lock``): while another run
    is in progress it raises ``RunInProgress`` before doing anything. Throughout, it publishes its
    run state (``vidpipe.runstate``) in ``build/run_state.json``; ``origin`` (``cli`` or ``ui``,
    default ``$VIDPIPE_RUN_ORIGIN``, else ``cli``) records who started it.

    ``resume_gate`` identifies a paused run and its gate (run ID, stage). It approves the
    existing outputs and resumes with that run's stage limit under the same writer lock.
    """
    who = _origin(origin)
    project = Project(project_dir)
    with writer_lock(project.root):
        if resume_gate is not None:
            run_id, stage = resume_gate
            paused = require_paused_gate(project.root, run_id, stage)
            GateKeeper(project, ArtifactStore(project)).approve(stage)
            until = paused.until
        return _run(
            project_dir,
            until=until,
            registry=registry,
            assembler=assembler,
            auto=auto,
            approve=approve,
            approver=approver,
            origin=who,
        )


def _origin(origin: Origin | str | None) -> Origin:
    try:
        return resolve_origin(origin)
    except ValueError as exc:
        raise PlanError([str(exc)]) from None


def _run(
    project_dir: Path,
    *,
    until: str | None,
    registry: Registry | None,
    assembler: Assembler | None,
    auto: bool,
    approve: Sequence[str],
    approver: Approver | None,
    origin: Origin,
    command: str = "run",
    shot: int | None = None,
) -> RunResult:
    project = Project(project_dir)
    names = _selected_stages(until)
    state = RunStatePublisher(
        project,
        origin=origin,
        stages=[(name, provider_label(name, project.config.providers.get(name))) for name in names],
        until=until,
        command=command,
        shot=shot,
    )
    watcher = StopWatcher(project.build, state)
    try:
        result = _run_stages(
            project, state, watcher, until, registry, assembler, auto, approve, approver
        )
    except PlanError as exc:
        state.fail("; ".join(exc.problems))
        raise
    except KeyboardInterrupt:
        state.fail("interrupted")
        raise
    except Exception as exc:
        state.fail(str(exc) or type(exc).__name__)
        raise
    finally:
        watcher.close()
    if not result.stopped:
        state.finish(paused_at=result.paused_at)
    return result


def _run_stages(
    project: Project,
    state: RunStatePublisher,
    watcher: StopWatcher,
    until: str | None,
    registry: Registry | None,
    assembler: Assembler | None,
    auto: bool,
    approve: Sequence[str],
    approver: Approver | None,
) -> RunResult:
    the_plan = plan(project.root, until=until, registry=registry, assembler=assembler)
    problems = [f"--approve: unknown stage {g!r}" for g in approve if g not in STAGE_NAMES]
    if not the_plan.ok or problems:
        raise PlanError([*the_plan.problems, *problems])

    ctx = _build_context(
        project,
        registry or default_registry(),
        assembler or FfmpegAssembler(),
        [],
        stop_now=watcher.now_requested,
    )
    keeper = GateKeeper(project, ctx.store)
    manifest = Manifest()
    paused_at: str | None = None
    wanted = set(_selected_stages(until))
    selected = [s for s in STAGES if s.name in wanted]
    # Totals known up front (from an earlier run's files); each is worked out again as its
    # stage begins, from what the stages before it wrote.
    state.totals({s.name: _artifact_count(s, ctx) for s in selected})

    def after_artifact() -> None:
        state.artifact(ctx.generated, ctx.reused)
        watcher.check()  # a stop ends the run here, between artifacts

    ctx.on_artifact = after_artifact
    for index, stage_obj in enumerate(selected):
        stage = stage_obj.name
        try:
            watcher.check()
        except RunStopped:
            state.stop()
            return RunResult(plan=the_plan, manifest=manifest, stopped=True)
        ctx.begin(stage)
        state.begin_stage(stage, _artifact_count(stage_obj, ctx))
        try:
            outputs = stage_obj.run(ctx)
        except (RunStopped, Cancelled) as exc:
            if isinstance(exc, Cancelled) and not watcher.now_requested():
                raise  # not ours to treat as a stop
            # The artifact in progress was finished (stop) or dropped (stop now); every other
            # artifact is in the ledger, so the next run picks up from here.
            state.stop(ctx.generated, ctx.reused)
            return RunResult(plan=the_plan, manifest=manifest, stopped=True)
        finally:
            # One model resident at a time: the stage's provider lets go (also after a failure).
            if used := ctx.providers.get(stage):
                used.release()
        selection = project.config.providers.get(stage)
        manifest.stages.append(
            StageRecord(
                stage=stage,
                provider=provider_label(stage, selection),
                outputs=outputs,
                generated=ctx.generated,
                reused=ctx.reused,
            )
        )
        project.write_model("manifest.json", manifest)
        gated = not auto and stage in project.config.gates and index < len(selected) - 1
        if gated and stage in approve:
            keeper.approve(stage)
        if gated and not keeper.passes(stage, approver):
            paused_at = stage
        # What this stage wrote may settle the size of the stages after it (shots, clips).
        state.totals({s.name: _artifact_count(s, ctx) for s in selected[index + 1 :]})
        state.end_stage(stage, ctx.generated, ctx.reused, paused=paused_at is not None)
        if paused_at is not None:
            break
    return RunResult(plan=the_plan, manifest=manifest, paused_at=paused_at)


def _artifact_count(stage: Stage, ctx: StageContext) -> int | None:
    try:
        return stage.artifact_count(ctx)
    except Exception:  # an earlier stage's output is not there yet: unknown for now
        return None


def approve(project_dir: Path, gates: Sequence[str]) -> None:
    """Approve what each gated stage has produced so far (``vidpipe approve``).

    Refused (``RunInProgress``) while a run holds the project's one-writer lock.
    """
    project = Project(project_dir)
    with writer_lock(project.root):
        keeper = GateKeeper(project, ArtifactStore(project))
        for gate in gates:
            if gate not in STAGE_NAMES:
                raise GateError(f"unknown stage {gate!r} (stages: {', '.join(STAGE_NAMES)})")
            keeper.approve(gate)


def reject_gate(project_dir: Path, run_id: str, stage: str) -> None:
    """Leave the specified run paused and clear any approval for its gate."""
    with writer_lock(project_dir):
        require_paused_gate(project_dir, run_id, stage)
        project = Project(project_dir)
        GateKeeper(project, ArtifactStore(project)).reject(stage)


def redo(
    project_dir: Path,
    *,
    shot: int,
    until: str | None = None,
    registry: Registry | None = None,
    assembler: Assembler | None = None,
    auto: bool = False,
    approve: Sequence[str] = (),
    approver: Approver | None = None,
    origin: Origin | str | None = None,
) -> RunResult:
    """Re-roll one shot (``vidpipe redo shot N``): new seed, then a normal run.

    The shot's re-roll count goes up in the ledger, which changes the seed (and so the input hash)
    of its keyframe and video, and the new video file changes what the assemblies read. A normal
    run then regenerates exactly those; every other shot's artifacts keep their records. Gates
    still apply: the new keyframe is shown at the keyframes gate again before it is animated.
    The redo holds the one-writer lock from the re-roll to the end of its run.
    """
    project = Project(project_dir)
    who = _origin(origin)
    with writer_lock(project.root):
        if not (project.build / "storyboard.json").is_file():
            raise PlanError(["nothing to redo: run the storyboard stage first"])
        storyboard = project.read_model("storyboard.json", Storyboard)
        if shot not in {s.id for s in storyboard.shots}:
            known = ", ".join(str(s.id) for s in storyboard.shots)
            raise PlanError([f"shot {shot} is not in the storyboard (shots: {known})"])
        the_plan = plan(project_dir, until=until, registry=registry, assembler=assembler)
        if not the_plan.ok:
            raise PlanError(the_plan.problems)

        ArtifactStore(project).reroll_shot(shot)
        return _run(
            project_dir,
            until=until,
            registry=registry,
            assembler=assembler,
            auto=auto,
            approve=approve,
            approver=approver,
            origin=who,
            command="redo",
            shot=shot,
        )
