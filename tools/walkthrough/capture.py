"""Capture the evidence for the walkthrough's live regeneration demo.

Copies a finished project to a scratch folder, re-runs it unchanged (everything skipped), changes
one Amharic narration line, re-runs it, and records what regenerated: terminal output, ledger
records before and after, artifact hashes, and screenshots of the web UI. Nothing in the source
project is touched. Needs network (Edge TTS, the Claude CLI for the back-translation check) but no
GPU, as long as the edit keeps the shot's narration short enough to fit its existing clip (see
README).

    uv run --with playwright python tools/walkthrough/capture.py --work DEMO --out CAPTURE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = Path.home() / ".t3" / "vidpipe-demos" / "lions-whisker-16x9"

# The edit: shot 15, the elder's advice, reworded to a shorter Amharic phrasing, same meaning.
# "Be as patient with the boy as you were with the lion."
OLD_LINE = "ለአንበሳው የታገሥሽውን ያህል ለልጁም ታገሺ።"
# "Just as you were patient with the lion, be patient with the boy too."
NEW_LINE = "ለአንበሳው እንደታገሥሽው ለልጁም ታገሺ።"
EDITED_FILE = "build/translation/am.json"
UI_PORT = 8777


def child_env() -> dict[str, str]:
    # This script itself runs under `uv run --with playwright`, whose VIRTUAL_ENV would make the
    # nested `uv run` print a warning into the captured output.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("VIRTUAL_ENV", None)
    return env


def vidpipe(project: Path, *args: str) -> tuple[str, int, float]:
    """Run ``vidpipe`` from the repo's locked environment with the project as working directory."""
    command = ["uv", "run", "--project", str(REPO), "--locked", "vidpipe", *args]
    env = child_env()
    start = time.monotonic()
    done = subprocess.run(
        command, cwd=project, env=env, capture_output=True, text=True, encoding="utf-8"
    )
    elapsed = time.monotonic() - start
    # vidpipe prints warnings on stderr and the stage table on stdout; a terminal shows them in this
    # order (warnings come first, as the run finishes).
    return done.stderr + done.stdout, done.returncode, elapsed


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(project: Path) -> dict[str, str]:
    found = {}
    for folder in ("build", "out"):
        for path in sorted((project / folder).rglob("*")):
            if path.is_file() and path.suffix in {".mp3", ".png", ".mp4", ".flac", ".json", ".srt"}:
                found[path.relative_to(project).as_posix()] = sha256(path)
    return found


def ledger(project: Path) -> dict[str, dict]:
    return json.loads((project / "build/ledger.json").read_text(encoding="utf-8"))["artifacts"]


def copy_project(source: Path, work: Path) -> Path:
    project = work / source.name
    if project.exists():
        shutil.rmtree(project)
    work.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, project)
    for leftover in ("run.lock", "run_state.json", "stop_request.json"):
        (project / "build" / leftover).unlink(missing_ok=True)
    return project


def settle(project: Path) -> None:
    """Bring the copied ledger up to date with the current code without regenerating any media.

    A code change since the original run can change an artifact's declared inputs (the fit planner's
    did). Re-running up to fit planning refreshes those records; the fit plan must come out
    byte-identical, or the full run would regenerate video on the GPU, so stop if it does not.
    """
    before = sha256(project / "build/fit_plan.json")
    output, code, _ = vidpipe(project, "run", ".", "--auto", "--until", "fit-planning")
    if code != 0:
        sys.exit(f"settling run failed:\n{output}")
    if sha256(project / "build/fit_plan.json") != before:
        sys.exit("the fit plan changed when re-planned: the demo would regenerate video; stopping")


def edit_line(project: Path) -> str:
    """Replace the line in place, byte for byte, so the file's line endings are kept."""
    path = project / EDITED_FILE
    data = path.read_bytes()
    old, new = OLD_LINE.encode(), NEW_LINE.encode()
    if data.count(old) != 1:
        sys.exit(f"expected the shot 15 line exactly once in {EDITED_FILE}")
    path.write_bytes(data.replace(old, new))
    before = data.decode("utf-8").splitlines()
    after = path.read_text(encoding="utf-8").splitlines()
    import difflib

    return "\n".join(
        difflib.unified_diff(
            before, after, f"a/{EDITED_FILE}", f"b/{EDITED_FILE}", n=3, lineterm=""
        )
    )


def screenshots(project: Path, out: Path) -> None:
    from playwright.sync_api import sync_playwright

    env = child_env()
    command = ["uv", "run", "--project", str(REPO), "--locked", "vidpipe", "ui", ".", "--port"]
    server = subprocess.Popen(
        [*command, str(UI_PORT)], cwd=project, env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        url = f"http://127.0.0.1:{UI_PORT}/"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(
                viewport={"width": 1600, "height": 900}, device_scale_factor=1.2,
                color_scheme="dark",
            )  # fmt: skip
            for _ in range(60):
                try:
                    page.goto(url)
                    break
                except Exception:
                    time.sleep(0.5)
            page.wait_for_selector("#stage-tab-assembly")
            page.wait_for_timeout(2000)
            page.screenshot(path=out / "ui_run.png")
            for stage in ("keyframes", "narration"):
                page.click(f"#stage-tab-{stage}")
                page.wait_for_timeout(1500)
                page.screenshot(path=out / f"ui_{stage}.png")
            page.get_by_text(NEW_LINE[:12]).first.scroll_into_view_if_needed()
            page.evaluate("window.scrollBy(0, 250)")
            page.wait_for_timeout(800)
            page.screenshot(path=out / "ui_narration_am.png")
            page.click("#view-tabs [data-view=config]")
            page.wait_for_function(
                "!document.body.innerText.includes('Loading the project config')", timeout=60000
            )
            page.wait_for_timeout(3000)
            page.screenshot(path=out / "ui_config.png")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--work", type=Path, required=True, help="scratch folder for the copy")
    parser.add_argument("--out", type=Path, required=True, help="where the evidence goes")
    parser.add_argument("--skip-ui", action="store_true")
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    print("copying", args.source)
    project = copy_project(args.source, args.work)
    settle(project)

    print("baseline run (nothing changed)")
    baseline, code, baseline_s = vidpipe(project, "run", ".", "--auto")
    if code != 0 or " ran (" in baseline:
        sys.exit(f"the unchanged re-run should skip every stage:\n{baseline}")
    plan, _, _ = vidpipe(project, "plan", ".")
    ledger_before, hashes_before = ledger(project), hashes(project)

    print("editing shot 15 and re-running")
    diff = edit_line(project)
    run, code, run_s = vidpipe(project, "run", ".", "--auto")
    if code != 0:
        sys.exit(f"the re-run failed:\n{run}")
    ledger_after, hashes_after = ledger(project), hashes(project)

    changed_records = [
        key
        for key, record in ledger_after.items()
        if ledger_before.get(key, {}).get("started_at") != record["started_at"]
    ]
    changed_files = sorted(k for k, v in hashes_after.items() if hashes_before.get(k) != v)
    evidence = {
        "project": project.as_posix(),
        "source": Path(args.source).as_posix(),
        "old_line": OLD_LINE,
        "new_line": NEW_LINE,
        "baseline_seconds": round(baseline_s, 1),
        "run_seconds": round(run_s, 1),
        "records_total": len(ledger_after),
        "records_changed": changed_records,
        "changed": {
            key: {"before": ledger_before.get(key), "after": ledger_after[key]}
            for key in changed_records
        },  # fmt: skip
        "gpu_seconds": sum(ledger_after[key]["gpu_seconds"] for key in changed_records),
        "files_changed": changed_files,
        "files_total": len(hashes_after),
        "hashes_before": hashes_before,
        "hashes_after": hashes_after,
    }
    texts = {"run_baseline.txt": baseline, "plan.txt": plan, "diff.txt": diff, "run_edit.txt": run}
    for name, text in texts.items():
        (out / name).write_text(text, encoding="utf-8")
    (out / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(run)
    print(f"{len(changed_records)} of {len(ledger_after)} records changed: {changed_records}")

    if not args.skip_ui:
        print("UI screenshots")
        screenshots(project, out)
    print("evidence in", out)


if __name__ == "__main__":
    main()
