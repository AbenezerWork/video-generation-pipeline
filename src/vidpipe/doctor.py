"""Read-only checks for the dependencies used by a vidpipe project."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from vidpipe.assembly import FfmpegAssembler, find_tool
from vidpipe.chain import build_provider
from vidpipe.comfy.client import ComfyClient, ComfyError
from vidpipe.comfy.provider import ComfyProvider
from vidpipe.comfy.workflow import WorkflowModel
from vidpipe.config import CONFIG_FILENAME, STAGE_KINDS, ProjectConfig, ProviderSelection
from vidpipe.contracts import ProjectContext, Provider, ProviderKind
from vidpipe.models import CONTRACT_STAGES
from vidpipe.project import Project
from vidpipe.providers.cli_text import CliTextProvider
from vidpipe.providers.edge import EdgeTTS
from vidpipe.registry import UnknownProvider, default_registry
from vidpipe.subtitles import font_languages, font_problems, resolve_fonts_dir
from vidpipe.text import FallbackTextProvider
from vidpipe.translate import TextTranslator


@dataclass(frozen=True)
class Check:
    name: str
    detail: str
    ok: bool = True
    #: For a failed provider check: what is wrong, in a few words ("CLI not found").
    problem: str = ""


def _media_checks(root: Path, config: ProjectConfig) -> list[Check]:
    problems = FfmpegAssembler().problems()
    checks = [Check("FFmpeg", problem, False) for problem in problems]
    if not problems:
        checks.append(
            Check(
                "FFmpeg",
                f"{find_tool('ffmpeg')} (libass, sidechaincompress, loudnorm); "
                f"ffprobe at {find_tool('ffprobe')}",
            )
        )
    languages = font_languages(config)
    if set(languages).intersection(config.subtitles.fonts):
        subtitles = config.subtitles.model_copy(update={"burn_in": True})
        problems = font_problems(subtitles, languages, root)
        checks.extend(Check("fonts", problem, False) for problem in problems)
        if not problems:
            checks.append(Check("fonts", str(resolve_fonts_dir(root, config.subtitles))))
    return checks


def _cli_members(provider: Provider[Any]) -> list[CliTextProvider]:
    if isinstance(provider, (FallbackTextProvider, TextTranslator)):
        return [p for p in provider.providers if isinstance(p, CliTextProvider)]
    return [provider] if isinstance(provider, CliTextProvider) else []


def _cli_check(provider: CliTextProvider) -> Check:
    if executable := shutil.which(provider.command):
        return Check(provider.name, f"executable found at {executable}")
    return Check(
        provider.name,
        f"executable {provider.command!r} not found. Install and sign in to {provider.binary}, "
        "or set the provider's `options.command` in vidpipe.yaml to its executable path.",
        False,
        "CLI not found",
    )


def _model_location(requirement: str) -> tuple[str, str]:
    category, _, name = requirement.replace("\\", "/").partition("/")
    # ComfyUI's public catalog uses the canonical folder names. The GGUF loader
    # scans the same folders but registers distinct categories for GGUF files.
    category = {"unet": "diffusion_models", "clip": "text_encoders"}.get(category, category)
    if name.lower().endswith(".gguf"):
        category = {"diffusion_models": "unet_gguf", "text_encoders": "clip_gguf"}.get(
            category, category
        )
    return category, name


def _model_checks(client: ComfyClient, workflows: list[WorkflowModel]) -> list[Check]:
    requirements = sorted({file for w in workflows for file in w.spec.requires.models})
    checks: list[Check] = []
    catalogs: dict[str, frozenset[str] | ComfyError] = {}
    for file in requirements:
        category, name = _model_location(file)
        if not category or not name:
            checks.append(
                Check(
                    "model",
                    f"{file!r}: use folder/filename in requires.models",
                    False,
                    "Workflow invalid",
                )
            )
            continue
        if category not in catalogs:
            try:
                catalogs[category] = client.model_names(category)
            except ComfyError as exc:
                catalogs[category] = exc
        catalog = catalogs[category]
        if isinstance(catalog, ComfyError):
            fix = (
                "load ComfyUI-GGUF and restart ComfyUI"
                if category in ("unet_gguf", "clip_gguf")
                else f"check the model folder {category!r} in your ComfyUI installation"
            )
            checks.append(
                Check(
                    "model",
                    f"cannot verify {file} at {client.url} ({catalog}); {fix}",
                    False,
                    "Model not verified",
                )
            )
        elif name in catalog:
            checks.append(Check("model", f"{file} at {client.url}"))
        else:
            checks.append(
                Check(
                    "model",
                    f"{file} missing at {client.url}. Download the file listed in the setup "
                    f"guide and place it at models/{file} or the matching extra model path.",
                    False,
                    "Model not found",
                )
            )
    return checks


def _comfy_checks(url: str, workflows: list[WorkflowModel]) -> list[Check]:
    try:
        client = ComfyClient(url, request_timeout_s=5)
        system = client.system_stats().get("system")
        version = (
            cast(dict[str, Any], system).get("comfyui_version")
            if isinstance(system, dict)
            else None
        )
        if not isinstance(version, str) or not version:
            raise ComfyError("/system_stats did not report a ComfyUI version")
    except (ComfyError, ValueError) as exc:
        return [
            Check(
                "ComfyUI",
                f"{url}: {exc}. Start ComfyUI or correct `comfyui.url` or the provider's "
                "`options.url` in vidpipe.yaml.",
                False,
                "ComfyUI not reachable",
            )
        ]

    checks = [Check("ComfyUI", f"{url} (version {version})")]
    for workflow in workflows:
        pin = workflow.spec.requires.comfyui
        if pin and version.removeprefix("v") != pin.removeprefix("v"):
            checks.append(
                Check(
                    "ComfyUI version",
                    f"{workflow.spec.name} is pinned to {pin}; {url} is running {version}. "
                    f"Use ComfyUI {pin} for this workflow.",
                    False,
                    "Wrong ComfyUI version",
                )
            )
    try:
        available = client.node_types()
    except ComfyError as exc:
        checks.append(
            Check(
                "ComfyUI nodes",
                f"{url}: {exc}; check the server's /object_info",
                False,
                "Nodes not verified",
            )
        )
    else:
        for workflow in workflows:
            if missing := sorted(workflow.node_types - available):
                packages = ", ".join(workflow.spec.requires.custom_nodes)
                fix = (
                    f"install or enable {packages} from the setup guide and restart ComfyUI"
                    if packages
                    else "use the ComfyUI version and node packages required by the workflow"
                )
                checks.append(
                    Check(
                        "ComfyUI nodes",
                        f"{workflow.spec.name} at {url} needs {', '.join(missing)}; {fix}",
                        False,
                        "Nodes missing",
                    )
                )
            else:
                checks.append(Check("ComfyUI nodes", f"{workflow.spec.name} at {url}"))
    return checks + _model_checks(client, workflows)


def check_environment(project_dir: Path | None = None) -> list[Check]:
    """Check a project's dependencies, or the default setup from outside a project."""
    root = Path.cwd() if project_dir is None else project_dir.resolve()
    from_contract = False
    if project_dir is not None or (root / CONFIG_FILENAME).is_file():
        project = Project(root)
        config = project.config
        from_contract = project.storyboard_contract is not None
    else:
        config = ProjectConfig.model_validate(
            {
                "languages": ["en", "am"],
                "providers": {"narration": "edge-tts", "keyframes": "comfyui-keyframer"},
            }
        )
    checks = _media_checks(root, config)
    context = ProjectContext(root=root, comfyui_url=config.comfyui.url)
    registry = default_registry()
    servers: dict[str, dict[Path, WorkflowModel]] = {}
    reported_clis: set[tuple[str, str]] = set()
    for stage, selection in config.providers.items():
        kind = STAGE_KINDS.get(stage)
        if kind is None or (from_contract and stage in CONTRACT_STAGES):
            continue
        if stage == "translation" and len(config.script_languages) == 1:
            continue
        try:
            provider = build_provider(registry, kind, selection)
            provider.attach(context)
        except (UnknownProvider, TypeError, ValueError, OSError) as exc:
            checks.append(Check(stage, f"{exc}. Check `providers.{stage}` in vidpipe.yaml.", False))
            continue
        if isinstance(provider, ComfyProvider):
            model = provider.model
            servers.setdefault(provider.client.url, {})[model.source] = model
        if isinstance(provider, EdgeTTS):
            checks.append(Check("edge-tts", "Python package available (online voices)"))
        for cli in _cli_members(provider):
            key = (cli.name, cli.command)
            if key not in reported_clis:
                reported_clis.add(key)
                checks.append(_cli_check(cli))
    for url, workflows in servers.items():
        checks.extend(_comfy_checks(url, list(workflows.values())))
    return checks


@dataclass(frozen=True)
class Readiness:
    """Whether one provider, as configured, would work now (the doctor's checks for it alone)."""

    ready: bool
    #: ``Ready``, or what is wrong in a few words (the first failed check's ``problem``).
    label: str
    #: The doctor's fix when not ready; what was found when ready.
    fix: str


#: Doctor checks already made, by ComfyUI server and workflow, so one readiness report asks
#: each server about each workflow once.
ComfyMemo = dict[tuple[str, Path], list[Check]]


def provider_checks(provider: Provider[Any], memo: ComfyMemo | None = None) -> list[Check]:
    """The doctor's checks for one attached provider (its CLIs, its ComfyUI server and models);
    empty when the doctor has nothing to check for it."""
    checks: list[Check] = []
    if isinstance(provider, ComfyProvider):
        key = (provider.client.url, provider.model.source)
        if memo is None or key not in memo:
            found = _comfy_checks(provider.client.url, [provider.model])
            if memo is None:
                return found
            memo[key] = found
        checks += memo[key]
    if isinstance(provider, EdgeTTS):
        checks.append(Check("edge-tts", "Python package available (online voices)"))
    checks += [_cli_check(cli) for cli in _cli_members(provider)]
    return checks


def provider_readiness(
    project_dir: Path,
    kind: ProviderKind,
    selection: ProviderSelection,
    *,
    comfyui_url: str | None = None,
    memo: ComfyMemo | None = None,
) -> Readiness:
    """Build ``selection`` as a run would (against ``project_dir``, with ``comfyui.url``) and run
    the doctor's checks for it. Read-only: nothing is generated or submitted."""
    context = ProjectContext(root=project_dir.resolve(), comfyui_url=comfyui_url)
    try:
        provider = build_provider(default_registry(), kind, selection)
        provider.attach(context)
    except (UnknownProvider, TypeError, ValueError, OSError) as exc:
        return Readiness(False, "Cannot configure", f"{exc}. Check the provider's options.")
    checks = provider_checks(provider, memo)
    if failed := next((check for check in checks if not check.ok), None):
        return Readiness(False, failed.problem or "Not ready", failed.detail)
    if checks:
        return Readiness(True, "Ready", "; ".join(check.detail for check in checks))
    note = "Fake provider for tests" if provider.fake else "Nothing to set up"
    return Readiness(True, "Ready", note)
