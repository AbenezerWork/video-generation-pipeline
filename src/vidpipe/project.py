"""The project directory: ``brief.md``, ``vidpipe.yaml`` and generated artifacts."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from vidpipe.config import CONFIG_FILENAME, ProjectConfig
from vidpipe.models import Brief, StoryboardContract

M = TypeVar("M", bound=BaseModel)


class ProjectError(Exception):
    """The project directory is missing something or contains something invalid."""


class Project:
    def __init__(self, root: Path, *, config: ProjectConfig | None = None) -> None:
        self.root = root.resolve()
        self.config = config if config is not None else self._load_config()

    # ------------------------------------------------------------------ source files

    def _load_config(self) -> ProjectConfig:
        path = self.root / CONFIG_FILENAME
        if not path.is_file():
            raise ProjectError(f"{self.root}: missing {CONFIG_FILENAME}")
        try:
            return ProjectConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (yaml.YAMLError, ValidationError) as exc:
            raise ProjectError(f"{path}: invalid config: {exc}") from exc

    def load_brief(self) -> Brief:
        path = self.root / "brief.md"
        if not path.is_file():
            raise ProjectError(f"{self.root}: missing brief.md")
        return Brief.from_markdown(path.read_text(encoding="utf-8"))

    @cached_property
    def storyboard_contract(self) -> StoryboardContract | None:
        path = self.root / "storyboard.json"
        try:
            contract = StoryboardContract.model_validate_json(path.read_text(encoding="utf-8"))
            for shot in contract.shots:
                if missing := sorted(set(self.config.script_languages) - shot.narration.keys()):
                    raise ValueError(
                        f"shot {shot.id} is missing narration for {', '.join(missing)}"
                    )
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise ProjectError(f"{path}: invalid storyboard contract: {exc}") from exc
        return contract

    # ------------------------------------------------------------------ artifacts

    @property
    def build(self) -> Path:
        return self.root / "build"

    @property
    def out(self) -> Path:
        return self.root / "out"

    def write_model(self, relative: str, model: BaseModel) -> str:
        """Persist a model under ``build/`` and return its path relative to ``build/``."""
        path = self.build / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        return relative

    def read_model(self, relative: str, model_type: type[M]) -> M:
        return model_type.model_validate_json((self.build / relative).read_text(encoding="utf-8"))

    def artifact_path(self, relative: str) -> Path:
        """Absolute path for a media artifact under ``build/`` (parent directory created)."""
        path = self.build / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
