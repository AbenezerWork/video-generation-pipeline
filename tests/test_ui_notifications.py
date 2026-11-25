"""Notification behavior in Playwright Chromium.

Run with ``uv run --with playwright pytest -m browser``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

# Playwright is installed only when running the opt-in browser tests.
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
pytest.importorskip("playwright.sync_api")
pytest.importorskip("uvicorn", reason="needs the optional ui extra")
pytest.importorskip("starlette", reason="needs the optional ui extra")

from playwright.sync_api import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    Page,
    Route,
    expect,
    sync_playwright,
)

from tests.conftest import MakeProject  # noqa: E402
from tests.ui_server import UiServer  # noqa: E402

pytestmark = pytest.mark.browser


@pytest.fixture
def ui(make_project: MakeProject) -> Iterator[UiServer]:
    server = UiServer(make_project(gates=["script"]))
    yield server
    server.stop()


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright, playwright.chromium.launch() as browser:
        yield browser.new_page()


def install_notification_api(page: Page, *, permission: str = "default", answer: str) -> None:
    page.add_init_script(f"""
        window.notices = [];
        window.permissionRequests = 0;
        window.Notification = class {{
            static permission = {permission!r};
            static async requestPermission() {{
                window.permissionRequests++;
                return this.permission = {answer!r};
            }}
            constructor(title) {{ window.notices.push(title); }}
        }};
    """)


@pytest.mark.needs_ffmpeg
def test_gate_pause_notifies_after_user_enables_browser_notifications(
    ui: UiServer, page: Page
) -> None:
    install_notification_api(page, answer="granted")
    page.goto(f"http://127.0.0.1:{ui.port}/")
    assert page.evaluate("window.permissionRequests") == 0

    page.get_by_role("button", name="Enable browser notifications").click(timeout=3000)
    expect(page.get_by_role("button", name="Disable browser notifications")).to_be_visible()
    assert page.evaluate("window.permissionRequests") == 1

    page.get_by_role("button", name="Start run").click()
    expect(page.locator("#run-status")).to_have_text("Paused", timeout=30000)
    assert page.evaluate("window.notices") == ["Run paused at a gate"]


def test_only_gate_failure_and_finish_notify_even_when_the_stream_replays_a_state(
    ui: UiServer, page: Page
) -> None:
    install_notification_api(page, answer="granted")
    batches = [
        [
            ("one", "running", 1),
            ("one", "running", 2),
            ("one", "stopping", 3),
            ("one", "stopped", 4),
            ("two", "paused", 5),
        ],
        [
            ("two", "paused", 5),
            ("two", "paused", 6),
            ("three", "running", 3),
            ("three", "failed", 3),
        ],
        [("three", "failed", 3), ("four", "finished", 4)],
        [("four", "finished", 4), ("five", "finished", 1)],
    ]
    armed = False

    def events(route: Route) -> None:
        body = "retry: 150\n\n"
        if armed and batches:
            for run_id, status, seq in batches.pop(0):
                state = {
                    "run_id": run_id,
                    "status": status,
                    "seq": seq,
                    "origin": "cli",
                    "started_at": "2026-11-26T09:00:00Z",
                    "paused_at": "script" if status == "paused" else None,
                    "stages": [],
                }
                body += f"event: run\nid: {run_id}:{seq}\ndata: {json.dumps(state)}\n\n"
        route.fulfill(content_type="text/event-stream", body=body)

    page.route("**/api/events", events)
    page.goto(f"http://127.0.0.1:{ui.port}/")
    page.get_by_role("button", name="Enable browser notifications").click()
    armed = True

    page.wait_for_function("window.notices.includes('Run finished')", timeout=5000)
    page.wait_for_function("window.notices.length >= 4", timeout=5000)
    assert page.evaluate("window.notices") == [
        "Run paused at a gate",
        "Run failed",
        "Run finished",
        "Run finished",
    ]


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize("permission", ["unsupported", "denied", "default"])
def test_notification_permission_fallback_leaves_the_run_view_usable(
    ui: UiServer, page: Page, permission: str
) -> None:
    if permission == "unsupported":
        page.add_init_script("delete window.Notification")
    else:
        install_notification_api(page, permission=permission, answer="denied")
    page.goto(f"http://127.0.0.1:{ui.port}/")

    if permission == "default":
        page.get_by_role("button", name="Enable browser notifications").click(timeout=3000)
    label = "unavailable" if permission == "unsupported" else "blocked"
    expect(page.get_by_role("button", name=f"Browser notifications {label}")).to_be_disabled(
        timeout=1000
    )
    if permission != "unsupported":
        assert page.evaluate("window.permissionRequests") == int(permission == "default")

    page.locator("#run-until").select_option("brief")
    page.get_by_role("button", name="Start run").click()
    expect(page.locator("#run-status")).to_have_text("Finished")
    if permission != "unsupported":
        assert page.evaluate("window.notices") == []


@pytest.mark.needs_ffmpeg
def test_browser_permission_alone_does_not_enable_notifications(ui: UiServer, page: Page) -> None:
    install_notification_api(page, permission="granted", answer="granted")
    page.goto(f"http://127.0.0.1:{ui.port}/")
    enable = page.get_by_role("button", name="Enable browser notifications")
    expect(enable).to_be_enabled()

    page.locator("#run-until").select_option("brief")
    page.get_by_role("button", name="Start run").click()
    expect(page.locator("#run-status")).to_have_text("Finished")
    assert page.evaluate("window.notices") == []

    page.reload()
    expect(page.locator("#run-status")).to_have_text("Finished")
    enable.click()
    assert page.evaluate("window.permissionRequests") == 0
    assert page.evaluate("window.notices") == []

    page.get_by_role("button", name="Disable browser notifications").click()
    page.get_by_role("button", name="Start run").click()
    expect(page.locator("#run-status")).to_have_text("Paused", timeout=30000)
    assert page.evaluate("window.notices") == []
