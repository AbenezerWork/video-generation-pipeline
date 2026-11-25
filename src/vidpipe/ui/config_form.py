"""The project config as the Config view edits it: validated as the CLI reads it, and rendered as
the YAML that saving would write (no web framework in here).

A **document** is the project config as plain data, the shape ``vidpipe.yaml`` has: only the keys
the creator set, so defaults stay implicit. :func:`check_config` validates a document with
:class:`~vidpipe.config.ProjectConfig` (the schema the CLI uses) and builds every stage's
provider as a run would, and renders it with :func:`render_yaml`: the file on disk with the
document's values merged in, keeping its comments and key order. Saving (a later feature) is
writing ``check.yaml`` once ``check.ok``.
"""

from __future__ import annotations

import io
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.representer import RoundTripRepresenter

from vidpipe.chain import build_provider
from vidpipe.config import CONFIG_FILENAME, STAGE_KINDS, ProjectConfig
from vidpipe.contracts import ProjectContext
from vidpipe.registry import UnknownProvider, default_registry
from vidpipe.stages import STAGE_NAMES

#: Friendlier words for pydantic's error types, keyed by type.
_MESSAGES = {"extra_forbidden": "Unknown setting"}


@dataclass(frozen=True)
class ConfigProblem:
    #: Dotted path of the setting (``mix.music_level``, ``providers.narration``); ``""`` for the
    #: whole config.
    path: str
    message: str


@dataclass(frozen=True)
class ConfigCheck:
    errors: list[ConfigProblem] = field(default_factory=list[ConfigProblem])
    #: What saving the document would write to ``vidpipe.yaml``.
    yaml: str = ""
    #: The config as the CLI reads it (defaults filled in), when it validates.
    effective: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [{"path": e.path, "message": e.message} for e in self.errors],
            "yaml": self.yaml,
            "effective": self.effective,
        }


def config_schema() -> dict[str, Any]:
    """JSON Schema of the project config, with the stage names a gate can name."""
    schema = ProjectConfig.model_json_schema()
    schema["properties"]["gates"]["items"]["enum"] = list(STAGE_NAMES)
    return schema


def read_document(project_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    """The project config file as a document, or ``None`` and what is wrong with the file."""
    path = project_dir / CONFIG_FILENAME
    if not path.is_file():
        return None, f"{path}: missing {CONFIG_FILENAME}"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, f"{path}: not valid YAML: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, f"{path}: the project config must be a mapping of settings"
    return cast(dict[str, Any], data), None


def check_config(project_dir: Path, document: Any) -> ConfigCheck:
    """Validate ``document`` as ``vidpipe run`` and ``vidpipe plan`` would and render its YAML."""
    if not isinstance(document, dict):
        return ConfigCheck([ConfigProblem("", "The project config must be a mapping of settings")])
    data = cast(dict[str, Any], document)
    rendered = render_yaml(project_dir, data)
    try:
        config = ProjectConfig.model_validate(data)
    except ValidationError as exc:
        return ConfigCheck(_schema_problems(exc), rendered)
    problems = _provider_problems(project_dir, config)
    problems += [
        ConfigProblem("gates", f"Unknown stage {gate!r} (stages: {', '.join(STAGE_NAMES)})")
        for gate in config.gates
        if gate not in STAGE_NAMES
    ]
    return ConfigCheck(problems, rendered, config.model_dump(mode="json"))


def _schema_problems(exc: ValidationError) -> list[ConfigProblem]:
    problems: list[ConfigProblem] = []
    for error in exc.errors():
        # Union and validator branches add non-key parts (``function-after[...]``); keep keys.
        parts = [str(p) for p in error["loc"] if isinstance(p, int) or "[" not in str(p)]
        message = _MESSAGES.get(error["type"], error["msg"])
        problems.append(ConfigProblem(".".join(parts), message.removeprefix("Value error, ")))
    return problems


def _provider_problems(project_dir: Path, config: ProjectConfig) -> list[ConfigProblem]:
    """Build each stage's provider as the pipeline does before a run (``pipeline.plan``)."""
    registry = default_registry()
    about = ProjectContext(root=project_dir.resolve(), comfyui_url=config.comfyui.url)
    problems: list[ConfigProblem] = []
    for stage, selection in config.providers.items():
        kind = STAGE_KINDS.get(stage)
        if kind is None:
            continue  # `song`: configurable, but not part of the stage graph yet
        try:
            build_provider(registry, kind, selection).attach(about)
        except UnknownProvider as exc:
            problems.append(ConfigProblem(f"providers.{stage}", str(exc)))
        except (TypeError, ValueError, OSError) as exc:
            problems.append(
                ConfigProblem(
                    f"providers.{stage}", f"cannot configure provider {selection.name!r}: {exc}"
                )
            )
    return problems


# ------------------------------------------------------------------------------ the YAML


class _CliYamlRepresenter(RoundTripRepresenter):
    """Keep scalar types compatible with PyYAML, the CLI's reader."""


def _represent_string(representer: RoundTripRepresenter, value: str) -> ScalarNode:
    plain = yaml.SafeLoader.yaml_implicit_resolvers.get(value[:1], ())
    style = "'" if any(pattern.match(value) for _, pattern in plain) else None
    return representer.represent_scalar(  # pyright: ignore[reportUnknownMemberType]
        "tag:yaml.org,2002:str", value, style=style
    )


_CliYamlRepresenter.add_representer(str, _represent_string)  # pyright: ignore[reportUnknownMemberType]


def _represent_float(representer: RoundTripRepresenter, value: float) -> ScalarNode:
    scalar = representer.represent_float(value)  # pyright: ignore[reportUnknownMemberType]
    spelling = cast(str, scalar.value)  # pyright: ignore[reportUnknownMemberType]
    # PyYAML needs a decimal point in the mantissa of scientific notation.
    if "e" in spelling and "." not in spelling:
        scalar.value = spelling.replace("e", ".0e", 1)
    return scalar


_CliYamlRepresenter.add_representer(float, _represent_float)  # pyright: ignore[reportUnknownMemberType]


def _round_trip() -> YAML:
    rt = YAML()
    rt.Representer = _CliYamlRepresenter
    rt.preserve_quotes = True
    rt.width = 4096  # never fold a long value onto a second line
    return rt


def render_yaml(project_dir: Path, document: dict[str, Any]) -> str:
    """``vidpipe.yaml`` with ``document``'s values: settings the document leaves out are removed,
    changed values replaced in place, new ones appended; comments and key order are kept. A
    document equal to the file gives the file unchanged."""
    path = project_dir / CONFIG_FILENAME
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    current, _ = read_document(project_dir)
    if current is not None and _same(current, document):
        return text
    rt = _round_trip()
    try:
        base = rt.load(text)  # pyright: ignore[reportUnknownMemberType]
    except YAMLError:
        base = None
    if not isinstance(base, CommentedMap):
        base = CommentedMap()
    _merge(base, document)
    out = io.StringIO()
    rt.dump(base, out)  # pyright: ignore[reportUnknownMemberType]
    return out.getvalue()


def _same(old: Any, new: Any) -> bool:
    """Equal as JSON (so ``True`` differs from ``1`` and ``1.0`` from ``1``)."""
    return json.dumps(old, sort_keys=True, default=str) == json.dumps(
        new, sort_keys=True, default=str
    )


def _merge(target: CommentedMap, new: dict[str, Any]) -> None:
    mapping = cast(dict[str, Any], target)
    for key in [k for k in mapping if k not in new]:
        del mapping[key]
    for key, value in new.items():
        old: Any = mapping.get(key)
        if key not in mapping:
            target[key] = value
        elif _same(old, value):
            continue  # keep the file's own spelling (quotes, flow style)
        elif isinstance(old, CommentedMap) and isinstance(value, dict):
            if old.anchor.value is not None:  # pyright: ignore[reportUnknownMemberType]
                # An alias elsewhere may still refer to the original mapping.
                old = deepcopy(old)
                old.yaml_set_anchor(None)  # pyright: ignore[reportUnknownMemberType]
                target[key] = old
            _merge(old, cast(dict[str, Any], value))
        elif isinstance(old, CommentedSeq) and isinstance(value, list):
            flow: Any = cast(Any, old).fa.flow_style()
            seq: Any = CommentedSeq(cast(list[Any], value))
            if flow:
                seq.fa.set_flow_style()
            target[key] = seq
        else:
            target[key] = value
