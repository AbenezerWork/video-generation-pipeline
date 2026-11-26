"""Each stage's provider choices for the Config view: every registered provider implementing the
stage's contract, with its declared options and its doctor readiness (no web framework in here).

New providers (built in or from a ``vidpipe.providers`` entry point) appear on their own: the
choices come from the registry, the options from ``Provider.declared_options`` and the readiness
from the doctor's checks (``vidpipe.doctor.provider_readiness``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from vidpipe.config import STAGE_KINDS, ProjectConfig, ProviderSelection
from vidpipe.contracts import ProviderKind
from vidpipe.doctor import ComfyMemo, provider_readiness
from vidpipe.registry import default_registry
from vidpipe.ui.config_form import read_document
from vidpipe.ui.summary import PHASES, stage_label

#: Stages that try their fallback providers in order (``script: [gemini-cli, claude-cli]``).
FALLBACK_STAGES = ("script", "storyboard", "translation")

#: Every stage with a provider, and ``song`` (configurable, not part of the stage graph yet).
PROVIDER_KINDS: dict[str, ProviderKind] = {**STAGE_KINDS, "song": ProviderKind.SONG}


def _contracts(stage: str) -> list[ProviderKind]:
    """The contracts whose providers can do a stage: translation also takes text providers."""
    kind = PROVIDER_KINDS[stage]
    return [kind, ProviderKind.TEXT] if kind is ProviderKind.TRANSLATION else [kind]


def _selection(document: Any, stage: str) -> ProviderSelection | None:
    providers: Any = (
        cast(dict[str, Any], document).get("providers") if isinstance(document, dict) else None
    )
    fields = (
        {stage: cast(dict[str, Any], providers)[stage]}
        if isinstance(providers, dict) and stage in providers
        else {}
    )
    try:
        # Keep the CLI's implicit text chains, even while another setting is being edited.
        return ProjectConfig.model_validate({"providers": fields}).providers.get(stage)
    except ValidationError:
        return None


def provider_choices(project_dir: Path, document: Any = None) -> dict[str, Any]:
    """Choices per stage for ``document`` (default: the project config on disk).

    Each choice's readiness is checked with the options the document gives that provider in the
    stage (as primary or fallback), else with none.
    """
    if document is None:
        document, _ = read_document(project_dir)
    comfyui_url = _comfyui_url(document)
    registry = default_registry()
    memo: ComfyMemo = {}
    stages: list[dict[str, Any]] = []
    for stage, kind in PROVIDER_KINDS.items():
        selection = _selection(document, stage)
        chain = [selection, *selection.fallback] if selection is not None else []
        choices: list[dict[str, Any]] = []
        seen: set[str] = set()
        for contract in _contracts(stage):
            for cls in registry.classes(contract):
                if cls.name in seen:
                    continue
                seen.add(cls.name)
                member = next((m for m in chain if m.name == cls.name), None)
                options = member.options if member is not None else {}
                readiness = provider_readiness(
                    project_dir,
                    kind,
                    ProviderSelection(name=cls.name, options=options),
                    comfyui_url=comfyui_url,
                    memo=memo,
                )
                choices.append(
                    {
                        "name": cls.name,
                        "contract": contract.value,
                        "fake": cls.fake,
                        "options": cls.declared_options(),
                        "readiness": {
                            "ready": readiness.ready,
                            "label": readiness.label,
                            "fix": readiness.fix,
                        },
                    }
                )
        stages.append(
            {
                "stage": stage,
                "label": stage_label(stage),
                "phase": PHASES.get(stage, "sound"),
                "contract": kind.value,
                "fallback": stage in FALLBACK_STAGES,
                "selected": selection.name if selection is not None else None,
                "selection": selection.model_dump(mode="json") if selection is not None else None,
                "choices": choices,
            }
        )
    return {"stages": stages}


def _comfyui_url(document: Any) -> str | None:
    if isinstance(document, dict):
        comfyui = cast(dict[str, Any], document).get("comfyui")
        if isinstance(comfyui, dict):
            url = cast(dict[str, Any], comfyui).get("url")
            return url if isinstance(url, str) else None
    return None
