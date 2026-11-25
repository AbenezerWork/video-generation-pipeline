"""Seam 1 against a real ComfyUI at http://127.0.0.1:8188 with the ADR 0001 models installed.

Run with ``uv run pytest -m integration -k comfy``. One job runs at a time and ComfyUI's memory is
freed after the stage. The conformance suite for ``comfyui-keyframer`` runs against the same server
(``tests/conformance/test_providers.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import MakeProject
from tests.test_keyframes_bible import cast_shots, ledger, png_size, run_keyframes
from vidpipe.cli import main
from vidpipe.comfy import ComfyClient

pytestmark = pytest.mark.integration


def test_the_sample_projects_keyframes_are_drawn_by_a_real_comfyui(
    make_project: MakeProject,
) -> None:
    project: Path = make_project(
        providers={"keyframes": "comfyui-keyframer"}, width=832, height=480
    )
    assert main(["run", str(project), "--until", "storyboard"]) == 0
    cast_shots(project, {"location": "highlands"}, {"character": "none"}, {})

    assert run_keyframes(project) == 0

    for shot in (1, 2, 3):
        record = ledger(project)[f"keyframes/shot_{shot:02d}"]
        assert png_size(project / "build" / "keyframes" / f"shot_{shot:02d}.png") == (832, 480)
        assert record["fallback"] is None
        assert 0 < record["gpu_seconds"] < 120
    references = [
        len(ledger(project)[f"keyframes/shot_{shot:02d}"]["data"]["references"])
        for shot in (1, 2, 3)
    ]
    assert references == [1, 0, 1]
    assert ComfyClient().queued_ids() == []
