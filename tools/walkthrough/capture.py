"""Capture a real English storyboard edit on a scratch copy of a finished project."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = Path.home() / ".t3" / "vidpipe-demos" / "lions-whisker-final-16x9"
OLD_LINE = "Be as patient with the boy as you were with the lion."
NEW_LINE = "Be as patient with the child as you were with the lion."
EDITED_FILE = "storyboard.json"
RUN_FILES = ("run.lock", "run_state.json", "stop_request.json", "runs.jsonl", ".env")


def child_env() -> dict[str, str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("VIRTUAL_ENV", None)
    env.pop("ADDIS_API_KEY", None)
    return env


def guarded_cli(args: list[str]) -> int:
    """Dispatch to vidpipe's CLI with live ComfyUI transport disabled."""
    from vidpipe.cli import main as cli_main
    from vidpipe.comfy.client import ComfyClient, ComfyUnreachable

    def offline(client: ComfyClient, path: str, **kwargs: object) -> bytes:
        raise ComfyUnreachable(f"walkthrough blocked live ComfyUI request to {path}")

    ComfyClient._request = offline
    os.environ.pop("ADDIS_API_KEY", None)
    return cli_main(args)


def vidpipe(project: Path, *args: str) -> tuple[str, int, float]:
    command = [
        "uv",
        "run",
        "--project",
        str(REPO),
        "--locked",
        "python",
        str(Path(__file__).resolve()),
        "--guarded-cli",
        *args,
    ]
    start = time.monotonic()
    done = subprocess.run(
        command, cwd=project, env=child_env(), capture_output=True, text=True, encoding="utf-8"
    )
    return done.stderr + done.stdout, done.returncode, time.monotonic() - start


def hashes(project: Path) -> dict[str, str]:
    paths = [
        path
        for folder in ("build", "out")
        for path in (project / folder).rglob("*")
        if path.is_file() and path.name not in RUN_FILES
    ]
    paths.append(project / EDITED_FILE)
    result = {}
    for path in sorted(paths):
        with path.open("rb") as stream:
            result[path.relative_to(project).as_posix()] = hashlib.file_digest(
                stream, "sha256"
            ).hexdigest()
    return result


def snapshot(project: Path, out: Path, label: str) -> tuple[dict, dict[str, str]]:
    ledger_bytes = (project / "build/ledger.json").read_bytes()
    (out / f"ledger_{label}.json").write_bytes(ledger_bytes)
    (out / f"fit_plan_{label}.json").write_bytes((project / "build/fit_plan.json").read_bytes())
    return json.loads(ledger_bytes)["artifacts"], hashes(project)


def copy_project(source: Path, work: Path) -> Path:
    state = json.loads((source / "build/run_state.json").read_text(encoding="utf-8"))
    if state["status"] != "finished":
        sys.exit(f"source render is {state['status']}: {source}")
    project = work / source.name
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(*RUN_FILES))
    return project


def edit_line(project: Path, new_line: str) -> str:
    path = project / EDITED_FILE
    data = path.read_bytes()
    shot = next(shot for shot in json.loads(data)["shots"] if shot["id"] == 15)
    old = f'"en": {json.dumps(OLD_LINE)}'.encode()
    new = f'"en": {json.dumps(new_line)}'.encode()
    if shot["narration"]["en"] != OLD_LINE or data.count(old) != 1:
        sys.exit(f"expected the shot 15 English line exactly once in {EDITED_FILE}")
    edited = data.replace(old, new)
    path.write_bytes(edited)
    return "\n".join(
        difflib.unified_diff(
            data.decode().splitlines(),
            edited.decode().splitlines(),
            f"a/{EDITED_FILE}",
            f"b/{EDITED_FILE}",
            n=2,
            lineterm="",
        )
    )


def capture(project: Path, out: Path, new_line: str) -> int:
    out.mkdir(parents=True, exist_ok=True)
    runlog = project / "runs.jsonl"

    def save(name: str, text: str) -> None:
        (out / name).write_text(text, encoding="utf-8")

    def calls() -> str:
        return runlog.read_text(encoding="utf-8") if runlog.is_file() else ""

    ledger_source, hashes_source = snapshot(project, out, "source")
    print("unchanged run", flush=True)
    baseline, baseline_code, baseline_s = vidpipe(project, "run", ".", "--auto")
    save("run_baseline.txt", baseline)
    baseline_calls = calls()
    save("runs_baseline.jsonl", baseline_calls)
    ledger_before, hashes_before = snapshot(project, out, "before")
    save("plan.txt", vidpipe(project, "plan", ".")[0])
    if baseline_code:
        print(baseline, file=sys.stderr)
        return baseline_code

    print("editing storyboard shot 15 and re-running", flush=True)
    save("diff.txt", edit_line(project, new_line))
    run, run_code, run_s = vidpipe(project, "run", ".", "--auto")
    save("run_edit.txt", run)
    save("runs_edit.jsonl", calls().removeprefix(baseline_calls))
    ledger_after, hashes_after = snapshot(project, out, "after")
    changed_records = [
        key
        for key in sorted(ledger_before.keys() | ledger_after.keys())
        if ledger_before.get(key) != ledger_after.get(key)
    ]
    evidence = {
        "project": project.as_posix(),
        "old_line": OLD_LINE,
        "new_line": new_line,
        "baseline_code": baseline_code,
        "baseline_seconds": round(baseline_s, 1),
        "baseline_records_changed": sorted(
            key
            for key in ledger_source.keys() | ledger_before.keys()
            if ledger_source.get(key) != ledger_before.get(key)
        ),
        "run_code": run_code,
        "run_seconds": round(run_s, 1),
        "records_total": len(ledger_after),
        "records_changed": changed_records,
        "changed": {
            key: {"before": ledger_before.get(key), "after": ledger_after.get(key)}
            for key in changed_records
        },
        "gpu_seconds": sum(
            ledger_after.get(key, {}).get("gpu_seconds", 0) for key in changed_records
        ),
        "files_changed": sorted(
            key
            for key in hashes_before.keys() | hashes_after.keys()
            if hashes_before.get(key) != hashes_after.get(key)
        ),
        "hashes_source": hashes_source,
        "hashes_before": hashes_before,
        "hashes_after": hashes_after,
    }
    save("evidence.json", json.dumps(evidence, ensure_ascii=False, indent=2))
    print(run)
    print(f"Changed ledger records: {changed_records}")
    return run_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="where the evidence goes")
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--work", type=Path, help="parent folder for a new project copy")
    location.add_argument(
        "--scratch-copy", type=Path, help="fresh scratch copy prepared separately"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--line", default=NEW_LINE, help="replacement English narration for shot 15"
    )
    args = parser.parse_args()
    project = args.scratch_copy or copy_project(args.source, args.work)
    if any(
        (project / name).exists()
        for name in ("build/run_state.json", "build/run.lock", "runs.jsonl")
    ):
        parser.error("the scratch copy must be fresh, with no run state, lock or model-call log")
    return capture(project.resolve(), args.out.resolve(), args.line)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--guarded-cli"]:
        sys.exit(guarded_cli(sys.argv[2:]))
    sys.exit(main())
