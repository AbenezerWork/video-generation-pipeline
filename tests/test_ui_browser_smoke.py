"""Exercise the Run and Config views together in Chromium against a fake project.

Run with ``uv run --with playwright pytest -m browser``.
"""

from __future__ import annotations

import re

import pytest

# Playwright is installed only when running the opt-in browser tests.
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
pytest.importorskip("playwright.sync_api")
pytest.importorskip("starlette", reason="needs the optional ui extra")
pytest.importorskip("uvicorn", reason="needs the optional ui extra")

from playwright.sync_api import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    expect,
    sync_playwright,
)

from tests.conftest import MakeProject  # noqa: E402
from tests.test_ui_run_controls import end_run  # noqa: E402
from tests.ui_server import UiServer  # noqa: E402
from vidpipe.project import Project  # noqa: E402


@pytest.mark.browser
def test_start_review_approve_and_save_project_config(make_project: MakeProject) -> None:
    project = make_project(gates=["script"])
    ui = UiServer(project)
    try:
        with sync_playwright() as playwright, playwright.chromium.launch() as browser:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui.port}/")
            rail = page.get_by_role("tablist", name="Stages")
            script = rail.get_by_role("tab", name=re.compile(r"^Script\b"))
            storyboard = rail.get_by_role("tab", name=re.compile(r"^Storyboard\b"))
            expect(script.get_by_text("Waiting", exact=True)).to_be_visible()
            expect(storyboard.get_by_text("Waiting", exact=True)).to_be_visible()

            page.get_by_label("Run through").select_option(label="Storyboard")
            page.get_by_role("button", name="Start run").click()
            expect(script.get_by_text("Paused", exact=True)).to_be_visible(timeout=10000)
            expect(storyboard.get_by_text("Waiting", exact=True)).to_be_visible()

            script.click()
            detail = page.get_by_role("tabpanel", name=re.compile(r"^Script\b"))
            expect(detail.get_by_role("heading", name="Script", exact=True)).to_be_visible()
            expect(
                detail.get_by_text(
                    "High in the Ethiopian highlands, a young goat herder watched his flock.",
                    exact=True,
                )
            ).to_be_visible()
            detail.get_by_role("button", name="Approve", exact=True).click()
            expect(storyboard.get_by_text("Done", exact=True)).to_be_visible(timeout=15000)
            expect(script.get_by_text("Reused", exact=True)).to_be_visible()
            expect(page.locator("#run-status")).to_have_text("Finished")

            page.get_by_role("tab", name="Config", exact=True).click()
            output_name = page.get_by_role("textbox", name="Output name")
            expect(output_name).to_have_value("demo")
            output_name.fill("smoke")
            estimate = page.get_by_role("region", name="Next run estimate")
            # Save only after the estimate for this edit has finished, not while it is pending.
            expect(estimate.get_by_text(re.compile(r"^Estimated GPU time is "))).to_be_visible(
                timeout=15000
            )
            expect(
                estimate.get_by_role("listitem").filter(
                    has_text=re.compile(r"^Assembly (will|may) regenerate")
                )
            ).to_be_visible()
            estimate.get_by_role("button", name="Save changes").click()
            expect(estimate.get_by_text("Project config saved.", exact=True)).to_be_visible()
            assert Project(project).config.output_name == "smoke"
    finally:
        ui.stop()
        end_run(project)
