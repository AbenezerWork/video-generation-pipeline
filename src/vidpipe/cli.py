"""``vidpipe`` command line."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from vidpipe import pipeline
from vidpipe.assembly import AssemblyError
from vidpipe.estimate import format_report
from vidpipe.gates import EXIT_PAUSED, Approver, GateError
from vidpipe.project import Project, ProjectError
from vidpipe.stages import STAGE_NAMES, StageError
from vidpipe.stop import EXIT_STOPPED, request_stop
from vidpipe.translate import report_lines


def _add_run_options(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--until", choices=STAGE_NAMES, help="stop after this stage (inclusive)")
    cmd.add_argument("--auto", action="store_true", help="skip every approval gate")
    cmd.add_argument(
        "--approve",
        action="append",
        default=[],
        metavar="GATE",
        help="approve this gate in advance when the run reaches it (repeatable)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vidpipe", description="Studio pipeline for short video.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the stage graph on a project directory")
    run.add_argument("project", type=Path, help="project directory (brief.md + vidpipe.yaml)")
    _add_run_options(run)
    plan = sub.add_parser("plan", help="show the plan and check capabilities; generates nothing")
    plan.add_argument("project", type=Path, help="project directory (brief.md + vidpipe.yaml)")
    plan.add_argument("--until", choices=STAGE_NAMES, help="stop after this stage (inclusive)")
    plan.add_argument("--json", action="store_true", help="print the plan and estimates as JSON")
    doctor = sub.add_parser("doctor", help="check the environment without running providers")
    doctor.add_argument(
        "project", type=Path, nargs="?", help="project directory (default: current directory)"
    )
    redo = sub.add_parser(
        "redo", help="re-roll one shot with a new seed and regenerate what follows"
    )
    redo.add_argument("what", choices=["shot"])
    redo.add_argument("number", type=int, help="shot id from the storyboard")
    redo.add_argument(
        "project", type=Path, nargs="?", default=Path("."), help="project directory (default: .)"
    )
    _add_run_options(redo)
    approve = sub.add_parser("approve", help="approve what a gated stage produced, so runs resume")
    approve.add_argument("project", type=Path, help="project directory")
    approve.add_argument("gates", nargs="+", metavar="GATE", help="stage the gate follows")
    stop = sub.add_parser(
        "stop", help="ask the run in progress to stop after the artifact it is working on"
    )
    stop.add_argument("project", type=Path, help="project directory")
    stop.add_argument(
        "--now",
        action="store_true",
        help="stop now: cancel the ComfyUI job in progress and discard that one artifact",
    )
    return parser


def _utf8_output() -> None:
    """Print Unicode (Ge'ez narration, say) whatever the console's code page is.

    A Windows console prints Unicode fine, but redirected output (a pipe, a file) falls back to
    the locale code page (cp1252), which cannot hold Ge'ez and would crash the command with
    ``UnicodeEncodeError``. Files vidpipe writes are always UTF-8, so output is made UTF-8 too.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            cast(Any, stream).reconfigure(encoding="utf-8", errors="replace")


def _drift_warnings(project: Path) -> list[str]:
    """Translations that need a human's review (back-translation drift), as warning lines."""
    return report_lines(Project(project))


def _interactive_approver(project: Path) -> Approver | None:
    """Ask at the terminal, but only when there is one (never block an unattended run)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None

    def ask(gate: str, outputs: Sequence[str]) -> bool:
        print(f"\ngate after {gate!r}: review", ", ".join(outputs))
        if STAGE_NAMES.index(gate) >= STAGE_NAMES.index("translation"):
            for warning in _drift_warnings(project):  # translations still flagged for review
                print(warning)
        return input(f"approve {gate}? [y/N] ").strip().lower() in ("y", "yes")

    return ask


def _report(result: pipeline.RunResult, project: Path) -> int:
    for record in result.manifest.stages:
        status = "skipped" if record.skipped else f"ran ({record.generated} generated)"
        print(f"{record.stage:<14}{record.provider or '-':<26}{status}")
    if any(record.stage == "translation" for record in result.manifest.stages):
        for warning in _drift_warnings(project):
            print(warning, file=sys.stderr)
    if result.stopped:
        print(f"\nstopped as asked; finished work is kept. Resume with: vidpipe run {project}")
        return EXIT_STOPPED
    if result.paused_at is None:
        return 0
    gate = result.paused_at
    print(f"\npaused: waiting for approval of {gate!r}. Review the files it produced, then either")
    print(f"  vidpipe approve {project} {gate}   and run again,")
    print(f"  vidpipe run {project} --approve {gate},")
    print(f"  or vidpipe run {project} --auto   (skips every gate).")
    return EXIT_PAUSED


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            from vidpipe.doctor import check_environment

            checks = check_environment(args.project)
            for check in checks:
                status = "OK" if check.ok else "FAIL"
                print(f"{status:<5} {check.name}: {check.detail}")
            failed = sum(not check.ok for check in checks)
            if failed:
                print(f"Doctor found {failed} problem(s).")
                return 1
            print("Doctor passed. All checked dependencies are available.")
            return 0
        if args.command == "plan":
            the_plan = pipeline.plan(args.project, until=args.until, estimate=True)
            if args.json:
                payload = the_plan.report.model_dump(mode="json") if the_plan.report else {}
                print(
                    json.dumps(
                        {
                            "ok": the_plan.ok,
                            "problems": the_plan.problems,
                            "gates": the_plan.gates,
                            **payload,
                        }
                    )
                )
            else:
                if the_plan.report:
                    print(format_report(the_plan.report))
                if the_plan.gates:
                    print(f"gates: after {', '.join(the_plan.gates)}")
            for problem in the_plan.problems:
                print(f"error: {problem}", file=sys.stderr)
            return 0 if the_plan.ok else 1
        if args.command == "stop":
            request = request_stop(args.project, now=args.now)
            how = (
                "cancels the ComfyUI job in progress and stops"
                if request.now
                else "stops after the artifact in progress"
            )
            print(f"stop requested: run {request.run_id} {how}")
            return 0
        if args.command == "approve":
            pipeline.approve(args.project, args.gates)
            print("approved", ", ".join(args.gates))
            return 0
        approver = _interactive_approver(args.project)
        if args.command == "redo":
            result = pipeline.redo(
                args.project,
                shot=args.number,
                until=args.until,
                auto=args.auto,
                approve=args.approve,
                approver=approver,
            )
        else:
            result = pipeline.run(
                args.project,
                until=args.until,
                auto=args.auto,
                approve=args.approve,
                approver=approver,
            )
        return _report(result, args.project)
    except pipeline.PlanError as exc:
        for problem in exc.problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    except (ProjectError, StageError, AssemblyError, GateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
