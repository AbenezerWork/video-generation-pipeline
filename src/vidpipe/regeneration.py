"""Estimate what an ordinary run can reuse, using the same inputs and ledger as the runner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from vidpipe.artifacts import Inputs, Made, Produced
from vidpipe.estimate import PlanReport, RegenerationReport, StageRegeneration
from vidpipe.project import Project
from vidpipe.stages import Stage, StageContext, StageError

# A miss can change the contents read by these stages. Until it runs, even a downstream
# artifact with matching inputs on disk can need regeneration.
DEPENDENCIES: dict[str, set[str]] = {
    "script": {"brief"},
    "translation": {"script"},
    "storyboard": {"script"},
    "narration": {"script", "translation", "storyboard"},
    "fit-planning": {"translation", "storyboard", "narration"},
    "keyframes": {"storyboard"},
    "video": {"storyboard", "fit-planning", "keyframes"},
    "music": {"brief", "fit-planning"},
    "assembly": {"storyboard", "fit-planning", "narration", "video", "music"},
}


class _NeedsArtifact(Exception):
    pass


def _refuse_generation() -> Made:
    raise _NeedsArtifact


class _ReadOnlyProject(Project):
    index_changed = False

    def write_model(self, relative: str, model: BaseModel) -> str:
        # Stages sometimes rebuild an index after reusing all their artifacts. Detect
        # a changed index so stages that read it are also included in the estimate.
        path = self.build / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != model.model_dump_json(
            indent=2
        ):
            self.index_changed = True
        return relative


class _Probe(StageContext):
    def produce(
        self,
        key: str,
        *,
        inputs: Inputs,
        make: Callable[[], Made],
        parameters: Mapping[str, Any] | None = None,
        seed: int | None = None,
        expected_outputs: Sequence[Path] = (),
        replace_edited: bool = False,
    ) -> Produced:
        # Only the reuse branch of ArtifactStore.produce can complete. On a miss,
        # it stops before calling the generator or writing an artifact or ledger.
        return super().produce(
            key,
            inputs=inputs,
            make=_refuse_generation,
            parameters=parameters,
            seed=seed,
            expected_outputs=expected_outputs,
            replace_edited=replace_edited,
        )


def _count(ctx: StageContext, stage: Stage) -> int | None:
    try:
        return stage.artifact_count(ctx)
    except (OSError, KeyError, ValueError, StageError):
        return None


def estimate_regeneration(
    ctx: StageContext, stages: list[Stage], report: PlanReport
) -> RegenerationReport:
    project = _ReadOnlyProject(ctx.project.root, config=ctx.project.config)
    probe = _Probe(project, ctx.providers, ctx.assembler)
    changed: set[str] = set()
    impacts: list[StageRegeneration] = []
    for stage, estimate in zip(stages, report.stages, strict=True):
        count = _count(probe, stage)
        if count == 0:
            continue
        possible = bool(changed & DEPENDENCIES.get(stage.name, set()))
        probe.begin(stage.name)
        project.index_changed = False
        if not possible:
            try:
                stage.run(probe)
            except _NeedsArtifact:
                pass
            except (OSError, ValueError, LookupError, StageError, StopIteration):
                possible = True
            else:
                if project.index_changed:
                    changed.add(stage.name)
                continue
        # Prefer the edited fit plan's clip estimate when its inputs may change.
        if count is None or (possible and stage.name == "video"):
            count = estimate.calls
        artifacts = None if count is None else count - probe.reused
        gpu = estimate.gpu_minutes
        if gpu is not None and estimate.calls and artifacts is not None:
            # The existing planner prices stages in aggregate, including providers
            # that charge per second. Allocate that estimate over the remaining work.
            provider_artifacts = artifacts
            if stage.name == "music" and project.config.music.candidates > 1:
                provider_artifacts -= 1  # the choice is recorded after the candidates
            gpu *= provider_artifacts / estimate.calls if stage.name != "translation" else 1
        impacts.append(
            StageRegeneration(
                stage=stage.name, artifacts=artifacts, gpu_minutes=gpu, possible=possible
            )
        )
        changed.add(stage.name)
    return RegenerationReport(
        stages=impacts,
        gpu_minutes=sum(impact.gpu_minutes or 0 for impact in impacts),
        complete=all(i.artifacts is not None and i.gpu_minutes is not None for i in impacts),
    )
