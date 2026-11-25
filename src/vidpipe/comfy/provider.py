"""The base of every ComfyUI-backed provider.

A concrete provider combines this with a contract class and only says how its request becomes
workflow values and how an output file becomes its result::

    class ComfyMusic(ComfyProvider[MusicCapabilities], MusicProvider):
        name = "comfyui-music"
        default_workflow = "music_ace_step"
        required_fields = ("prompt", "seed", "seconds")

        def declare_capabilities(self, model: WorkflowModel) -> MusicCapabilities:
            return MusicCapabilities.model_validate(model.spec.capabilities)

        def compose(self, request: MusicRequest) -> MusicResult:
            outcome = self.run_workflow(
                {"prompt": request.prompt, "seconds": request.duration_s}, seed=request.seed
            )
            path = self.save_output(outcome, request.output_path)
            return MusicResult(path=path, ..., record=self.record(outcome, images=0))

Options (``options:`` in ``vidpipe.yaml``, all optional):

* ``workflow``: a bundled model's name or a mapping file path (relative to the project);
* ``settings``: values for the mapping's fields, e.g. ``{reference_megapixels: 0.25}``;
* ``url``: ComfyUI's address (default: the project's ``comfyui.url``, else 127.0.0.1:8188);
* ``retries`` (2), ``timeout_s`` (from the mapping), ``poll_s`` (0.5).
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from vidpipe.comfy.client import DEFAULT_URL, ComfyClient
from vidpipe.comfy.jobs import RETRIES, JobOutcome, run_job
from vidpipe.comfy.workflow import WorkflowError, WorkflowModel, locate_mapping
from vidpipe.contracts import (
    Capabilities,
    GenerationError,
    GenerationRecord,
    ProjectContext,
    Provider,
    UnsupportedRequest,
)


class ComfyProvider[C: Capabilities](Provider[C]):
    #: The bundled mapping used when ``options.workflow`` is not set.
    default_workflow: ClassVar[str]
    #: Values every variant of a workflow must take for this provider to use it.
    required_fields: ClassVar[tuple[str, ...]] = ("seed",)
    uses_gpu = True
    unhashed_options = frozenset({"url", "workflow", "retries", "timeout_s", "poll_s"})

    def __init__(
        self,
        *,
        workflow: str | None = None,
        url: str | None = None,
        settings: Mapping[str, Any] | None = None,
        retries: int = RETRIES,
        timeout_s: float | None = None,
        poll_s: float = 0.5,
    ) -> None:
        given = {
            "workflow": workflow,
            "url": url,
            "settings": dict(settings) if settings is not None else None,
            "retries": retries,
            "timeout_s": timeout_s,
            "poll_s": poll_s,
        }
        super().__init__(**{k: v for k, v in given.items() if v is not None})
        if retries < 0:
            raise ValueError("retries cannot be negative")
        self.retries = retries
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self._settings = dict(settings or {})
        self._url = url
        self.client = ComfyClient(url or DEFAULT_URL)
        self._reference = workflow or self.default_workflow
        self._model: WorkflowModel | None = None
        self._submitted = False
        path = locate_mapping(self._reference)
        # A project-relative mapping may only be found once the pipeline attaches the project.
        if path.is_file() or path.is_absolute():
            self._load(path)

    def attach(self, context: ProjectContext) -> None:
        self.client = ComfyClient(self._url or context.comfyui_url or DEFAULT_URL)
        self._load(locate_mapping(self._reference, context.root))

    def _load(self, path: Path) -> None:
        model = WorkflowModel.load(path)
        model.require(self.required_fields)
        if unknown := sorted(set(self._settings) - set(model.spec.fields)):
            raise WorkflowError(
                f"settings {unknown} are not fields of {path.name} "
                f"(fields: {', '.join(sorted(model.spec.fields))})"
            )
        self._model = model
        self.capabilities = self.declare_capabilities(model)
        self.cost = model.spec.cost

    @abstractmethod
    def declare_capabilities(self, model: WorkflowModel) -> C:
        """What this provider can do with ``model`` (usually from its mapping file)."""

    @property
    def model(self) -> WorkflowModel:
        if self._model is None:
            self._load(locate_mapping(self._reference))
        assert self._model is not None
        return self._model

    @property
    def settings(self) -> dict[str, Any]:
        """The mapping's default settings with the project's overrides."""
        return {**self.model.spec.settings, **self._settings}

    def fingerprint(self) -> dict[str, Any]:
        options = {k: v for k, v in self.options.items() if k not in self.unhashed_options}
        return {
            "name": self.name,
            "workflow": self.model.digest,
            "settings": self.settings,
            "options": options,
        }

    # -------------------------------------------------------------------------------- running

    def run_workflow(
        self,
        values: Mapping[str, Any],
        *,
        seed: int,
        images: Sequence[Path] = (),
        extras: Mapping[str, Any] | None = None,
    ) -> JobOutcome:
        """Run one job, with retries. ``extras`` may override settings (unknown ones: ignored)."""
        model = self.model
        if len(images) not in model.image_counts:
            raise UnsupportedRequest(
                f"{model.spec.name} takes {model.image_counts} input images, not {len(images)}"
            )
        if missing := [str(p) for p in images if not p.is_file()]:
            raise GenerationError(f"input images do not exist: {', '.join(missing)}")
        overrides = {k: v for k, v in (extras or {}).items() if k in model.spec.fields}
        self._submitted = True
        return run_job(
            self.client,
            model,
            {**self.settings, **overrides, **values},
            seed=seed,
            images=images,
            retries=self.retries,
            timeout_s=self.timeout_s,
            poll_s=self.poll_s,
        )

    def save_output(self, outcome: JobOutcome, requested: Path) -> Path:
        """Write the job's first output file at ``requested``, with the output's own suffix."""
        name, data = outcome.files[0]
        path = requested.with_suffix(Path(name).suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def record(self, outcome: JobOutcome, *, images: int) -> GenerationRecord:
        """What the job did, for the artifact's ledger record."""
        settings = {
            field: value
            for field, value in outcome.values.items()
            if field != "prompt" and self.model.value(field, outcome.values, images) is not None
        }
        return GenerationRecord(
            seed=outcome.seed,
            fallback=outcome.fallback,
            gpu_seconds=outcome.gpu_seconds,
            details={
                "workflow": self.model.workflow_name(images),
                "settings": settings,
                "attempts": outcome.attempt_log(),
            },
        )

    def release(self) -> None:
        """Unload ComfyUI's models if this provider ran anything since the last release."""
        if self._submitted:
            self._submitted = False
            self.client.free()
