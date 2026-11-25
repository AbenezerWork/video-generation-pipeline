"""The project config as the Config view edits it: validated as the CLI reads it, and rendered as
the YAML that saving would write (no web framework in here).

A **document** is the project config as plain data, the shape ``vidpipe.yaml`` has: only the keys
the creator set, so defaults stay implicit. :func:`check_config` validates a document with
:class:`~vidpipe.config.ProjectConfig` (the schema the CLI uses) and builds every stage's
provider as a run would, and renders it with :func:`render_yaml`: the file on disk with the
document's values merged in, keeping its comments and key order.
"""

from __future__ import annotations

import hashlib
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
from vidpipe.runstate import config_hash
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


def revision_of(source: str) -> str:
    """Fingerprint of the whole YAML document, including hand-written comments."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def config_file_state(project_dir: Path) -> dict[str, str | None]:
    try:
        source = (project_dir / CONFIG_FILENAME).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {"revision": None, "config_hash": None}
    document, _ = read_document(project_dir, source=source)
    try:
        current = config_hash(ProjectConfig.model_validate(document))
    except ValidationError:
        current = None
    return {"revision": revision_of(source), "config_hash": current}


def read_document(
    project_dir: Path, *, source: str | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """The project config file as a document, or ``None`` and what is wrong with the file."""
    path = project_dir / CONFIG_FILENAME
    if source is None and not path.is_file():
        return None, f"{path}: missing {CONFIG_FILENAME}"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8") if source is None else source)
    except yaml.YAMLError as exc:
        return None, f"{path}: not valid YAML: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, f"{path}: the project config must be a mapping of settings"
    return cast(dict[str, Any], data), None


def check_config(project_dir: Path, document: Any, *, source: str | None = None) -> ConfigCheck:
    """Validate ``document`` as ``vidpipe run`` and ``vidpipe plan`` would and render its YAML."""
    if not isinstance(document, dict):
        return ConfigCheck([ConfigProblem("", "The project config must be a mapping of settings")])
    data = cast(dict[str, Any], document)
    rendered = render_yaml(project_dir, data, source=source)
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


def render_yaml(project_dir: Path, document: dict[str, Any], *, source: str | None = None) -> str:
    """``vidpipe.yaml`` with ``document``'s values: settings the document leaves out are removed,
    changed values replaced in place, new ones appended; comments and key order are kept. A
    document equal to the file gives the file unchanged."""
    path = project_dir / CONFIG_FILENAME
    text = (
        source
        if source is not None
        else (path.read_text(encoding="utf-8") if path.is_file() else "")
    )
    current, _ = read_document(project_dir, source=text)
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
            if old.anchor.value is not None:  # pyright: ignore[reportUnknownMemberType]
                old = deepcopy(old)
                old.yaml_set_anchor(None)  # pyright: ignore[reportUnknownMemberType]
                target[key] = old
            _merge_sequence(old, cast(list[Any], value))
        else:
            target[key] = value


def _merge_sequence(target: CommentedSeq, new: list[Any]) -> None:
    items = cast(list[Any], target)
    comments = cast(dict[int, Any], target.ca.items)  # pyright: ignore[reportUnknownMemberType]
    for index, value in enumerate(new):
        match = next((i for i in range(index, len(items)) if _same(items[i], value)), None)
        if match == index:
            continue
        if match is not None:
            # ruamel shifts comments on removal and insertion. Carry the moved entry's
            # comment over explicitly, including when the entry is a whole mapping.
            comment = comments.get(match)
            item = items.pop(match)
            items.insert(index, item)
            if comment is not None:
                comments[index] = comment
        elif index == len(items) or any(_same(items[index], later) for later in new[index + 1 :]):
            items.insert(index, value)
        elif isinstance(items[index], CommentedMap) and isinstance(value, dict):
            # Merge a changed entry in place, preserving comments on its options.
            entry = cast(CommentedMap, items[index])
            if entry.anchor.value is not None:  # pyright: ignore[reportUnknownMemberType]
                entry = deepcopy(entry)
                entry.yaml_set_anchor(None)  # pyright: ignore[reportUnknownMemberType]
                items[index] = entry
            _merge(entry, cast(dict[str, Any], value))
        else:
            items[index] = value
    del items[len(new) :]
