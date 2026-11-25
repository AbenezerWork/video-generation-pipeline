"""A ComfyUI model as data: API-format workflow JSON files plus a mapping file.

The mapping file (``<name>.mapping.yaml``, format in ``workflows/README.md``) says which workflow to
use for how many input images, which node inputs each value is written to, where the result comes
out, what to lower after an out-of-memory error, and what the model can do and costs. Adding a model
is a workflow plus a mapping: no Python.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vidpipe.contracts import CostModel

MAPPING_SUFFIX = ".mapping.yaml"

#: An API-format ComfyUI workflow: node id -> ``{"class_type": ..., "inputs": {...}}``.
Graph = dict[str, dict[str, Any]]


class WorkflowError(ValueError):
    """A mapping file or one of its workflows is missing or inconsistent."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Variant(_Strict):
    #: How many input images this workflow takes.
    images: int = Field(ge=0)
    #: The workflow file, relative to the mapping file.
    workflow: str


class Output(_Strict):
    #: The node whose results are fetched, and the key they appear under in ``/history``.
    node: str
    key: str = "images"


class StepDown(_Strict):
    """One rung of the out-of-memory ladder: lower some values, or take a smaller output size."""

    #: Field -> lower value. Applies when it lowers at least one and raises none.
    set: dict[str, float] | None = None
    #: Sizes to choose from: the largest one smaller than the current size on neither side bigger.
    smaller_size: tuple[tuple[int, int], ...] | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> StepDown:
        if (self.set is None) == (self.smaller_size is None):
            raise ValueError("an oom_step_down entry has either `set` or `smaller_size`")
        return self


class Requirements(_Strict):
    """What the ComfyUI installation needs (for setup docs and ``doctor``)."""

    comfyui: str | None = None
    custom_nodes: tuple[str, ...] = ()
    #: Model files, as ``<ComfyUI models folder>/<file name>``.
    models: tuple[str, ...] = ()


class MappingFile(_Strict):
    name: str
    variants: tuple[Variant, ...] = Field(min_length=1)
    #: ``<node>.inputs.<input>`` for each input image, in order.
    images: tuple[str, ...] = ()
    #: Value name -> the node inputs it is written to.
    fields: dict[str, tuple[str, ...]]
    outputs: Output
    #: Default values for fields, overridable per project (``options.settings``).
    settings: dict[str, Any] = Field(default_factory=dict[str, Any])
    oom_step_down: tuple[StepDown, ...] = ()
    #: How long one job may take, queueing included.
    timeout_s: float = Field(default=600, gt=0)
    #: Validated by the provider against its contract's capability model.
    capabilities: dict[str, Any] = Field(default_factory=dict[str, Any])
    cost: CostModel = CostModel()
    requires: Requirements = Requirements()


def bundled_workflows_dir() -> Path:
    """The workflows shipped with vidpipe: in an installed package, or in a checkout."""
    here = Path(__file__).resolve()
    packaged = here.parents[1] / "_workflows"
    return packaged if packaged.is_dir() else here.parents[3] / "workflows"


def locate_mapping(reference: str, base: Path | None = None) -> Path:
    """The mapping file for ``reference``: a bundled model's name, or a path to a ``.yaml`` file
    (relative to ``base``, usually the project directory)."""
    if reference.lower().endswith((".yaml", ".yml")):
        path = Path(reference).expanduser()
        return path if base is None or path.is_absolute() else base / path
    return bundled_workflows_dir() / f"{reference}{MAPPING_SUFFIX}"


def _split(target: str) -> tuple[str, str]:
    node, _, name = target.partition(".inputs.")
    if not node or not name:
        raise WorkflowError(f"field target {target!r} is not `<node id>.inputs.<input>`")
    return node, name


def _exists(graph: Graph, target: str) -> bool:
    node, name = _split(target)
    return node in graph and name in graph[node]["inputs"]


def _number(value: float) -> str:
    return f"{value:g}"


class WorkflowModel:
    """A loaded and checked mapping file with its workflows."""

    def __init__(self, spec: MappingFile, graphs: Mapping[int, Graph], source: Path) -> None:
        self.spec = spec
        self.source = source
        self._graphs = dict(graphs)
        self._check()

    @classmethod
    def load(cls, path: Path) -> WorkflowModel:
        if not path.is_file():
            known = sorted(
                p.name.removesuffix(MAPPING_SUFFIX)
                for p in bundled_workflows_dir().glob(f"*{MAPPING_SUFFIX}")
            )
            raise WorkflowError(
                f"no workflow mapping at {path} (bundled: {', '.join(known) or 'none'})"
            )
        try:
            spec = MappingFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (yaml.YAMLError, ValidationError) as exc:
            raise WorkflowError(f"{path}: invalid mapping: {exc}") from exc
        graphs: dict[int, Graph] = {}
        for variant in spec.variants:
            file = path.parent / variant.workflow
            try:
                graph: Graph = json.loads(file.read_text(encoding="utf-8"))
                graphs[variant.images] = {
                    key: {"class_type": node["class_type"], "inputs": node["inputs"]}
                    for key, node in graph.items()
                }
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise WorkflowError(f"{file}: not an API-format workflow: {exc!r}") from exc
        return cls(spec, graphs, path)

    def _check(self) -> None:
        where = self.source
        counts = [v.images for v in self.spec.variants]
        if len(set(counts)) != len(counts):
            raise WorkflowError(f"{where}: two variants take the same number of images")
        for target in (*self.spec.images, *(t for ts in self.spec.fields.values() for t in ts)):
            if not any(_exists(graph, target) for graph in self._graphs.values()):
                raise WorkflowError(f"{where}: no workflow has the node input {target!r}")
        for count, graph in self._graphs.items():
            if count > len(self.spec.images):
                raise WorkflowError(f"{where}: `images` has no slot for image {count}")
            for target in self.spec.images[:count]:
                if not _exists(graph, target):
                    raise WorkflowError(
                        f"{where}: the {count}-image workflow has no node input {target!r}"
                    )
            if self.spec.outputs.node not in graph:
                raise WorkflowError(
                    f"{where}: the {count}-image workflow has no output node "
                    f"{self.spec.outputs.node!r}"
                )
        known = set(self.spec.fields)
        used = set(self.spec.settings)
        for step in self.spec.oom_step_down:
            used |= set(step.set or {})
            if step.smaller_size is not None:
                used |= {"width", "height"}
        if unknown := sorted(used - known):
            raise WorkflowError(f"{where}: settings/oom_step_down name unmapped fields: {unknown}")

    # ------------------------------------------------------------------------------ describing

    @property
    def max_images(self) -> int:
        return max(self._graphs)

    @property
    def image_counts(self) -> list[int]:
        return sorted(self._graphs)

    @property
    def node_types(self) -> frozenset[str]:
        """Node classes needed across every variant of this workflow."""
        return frozenset(
            str(node["class_type"]) for graph in self._graphs.values() for node in graph.values()
        )

    def workflow_name(self, images: int) -> str:
        return next(v.workflow for v in self.spec.variants if v.images == images)

    @property
    def digest(self) -> str:
        """Hash of everything here that decides the output (not costs, limits or timeouts)."""
        spec = self.spec
        content = {
            "graphs": {str(count): graph for count, graph in self._graphs.items()},
            "images": spec.images,
            "fields": spec.fields,
            "outputs": spec.outputs.model_dump(),
            "settings": spec.settings,
        }
        text = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def require(self, fields: Sequence[str]) -> None:
        """Every variant must take each of these values."""
        for count, graph in self._graphs.items():
            for field in fields:
                if not any(_exists(graph, t) for t in self.spec.fields.get(field, ())):
                    raise WorkflowError(
                        f"{self.source}: the {count}-image workflow has no field {field!r}"
                    )

    # ------------------------------------------------------------------------------- building

    def build(self, values: Mapping[str, Any], image_names: Sequence[str] = ()) -> Graph:
        """The workflow for ``len(image_names)`` input images with ``values`` written into it.

        Values the mapping does not name, or whose nodes this variant lacks, are left out.
        """
        graph = copy.deepcopy(self._graphs[len(image_names)])
        writes = [
            (target, value)
            for field, value in values.items()
            for target in self.spec.fields.get(field, ())
        ]
        writes += list(zip(self.spec.images, image_names, strict=False))
        for target, value in writes:
            if _exists(graph, target):
                node, name = _split(target)
                graph[node]["inputs"][name] = value
        return graph

    def value(self, field: str, values: Mapping[str, Any], images: int) -> Any:
        """What ``field`` will be in a job: from ``values``, else the workflow's own value.
        ``None`` when this variant does not take it."""
        graph = self._graphs[images]
        for target in self.spec.fields.get(field, ()):
            if _exists(graph, target):
                node, name = _split(target)
                return values.get(field, graph[node]["inputs"][name])
        return None

    def step_down(
        self, values: Mapping[str, Any], images: int
    ) -> tuple[dict[str, Any], str] | None:
        """The first rung of the ladder that lowers something: ``(new values, description)``.

        A rung naming a value this variant does not take as a number is passed over.
        """

        def numbers(*fields: str) -> dict[str, float] | None:
            found = {f: self.value(f, values, images) for f in fields}
            usable = all(isinstance(v, int | float) for v in found.values())
            return cast(dict[str, float], found) if usable else None

        for step in self.spec.oom_step_down:
            if step.set is not None:
                now = numbers(*step.set)
                if now is None or any(step.set[f] > v for f, v in now.items()):
                    continue
                lowered = {f: step.set[f] for f, v in now.items() if step.set[f] < v}
                if not lowered:
                    continue
                changed = {f: int(v) if v.is_integer() else v for f, v in lowered.items()}
                note = ", ".join(
                    f"{f} {_number(now[f])} -> {_number(v)}" for f, v in changed.items()
                )
                return {**values, **changed}, note
            size = numbers("width", "height")
            if size is None:
                continue
            width, height = size["width"], size["height"]
            smaller = [
                (w, h)
                for w, h in step.smaller_size or ()
                if w <= width and h <= height and w * h < width * height
            ]
            if smaller:
                w, h = max(smaller, key=lambda s: s[0] * s[1])
                note = f"size {_number(width)}x{_number(height)} -> {w}x{h}"
                return {**values, "width": w, "height": h}, note
        return None
