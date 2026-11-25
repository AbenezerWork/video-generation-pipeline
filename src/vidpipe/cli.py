"""``vidpipe`` command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from vidpipe import pipeline
from vidpipe.artifacts import ArtifactStore
from vidpipe.assembly import AssemblyError
from vidpipe.gates import EXIT_PAUSED, Approver, GateError, GateKeeper
from vidpipe.project import Project, ProjectError
from vidpipe.stages import STAGE_NAMES, StageError


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
    approve = sub.add_parser("approve", help="approve what a gated stage produced, so runs resume")
    approve.add_argument("project", type=Path, help="project directory")
    approve.add_argument("gates", nargs="+", metavar="GATE", help="stage the gate follows")
    return parser


def _interactive_approver() -> Approver | None:
    """Ask at the terminal, but only when there is one (never block an unattended run)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None

    def ask(gate: str, outputs: Sequence[str]) -> bool:
        print(f"\ngate after {gate!r}: review", ", ".join(outputs))
        return input(f"approve {gate}? [y/N] ").strip().lower() in ("y", "yes")

    return ask


def _report(result: pipeline.RunResult, project: Path) -> int:
    for record in result.manifest.stages:
        status = "skipped" if record.skipped else f"ran ({record.generated} generated)"
        print(f"{record.stage:<14}{record.provider or '-':<20}{status}")
    if result.paused_at is None:
        return 0
    gate = result.paused_at
    print(f"\npaused: waiting for approval of {gate!r}. Review the files it produced, then either")
    print(f"  vidpipe approve {project} {gate}   and run again,")
    print(f"  vidpipe run {project} --approve {gate},")
    print(f"  or vidpipe run {project} --auto   (skips every gate).")
    return EXIT_PAUSED


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            the_plan = pipeline.plan(args.project, until=args.until)
            for stage in the_plan.stages:
                print(f"{stage.name:<14}{stage.provider or '-'}")
            if the_plan.gates:
                print(f"gates: after {', '.join(the_plan.gates)}")
            for problem in the_plan.problems:
                print(f"error: {problem}", file=sys.stderr)
            return 0 if the_plan.ok else 1
        if args.command == "approve":
            project = Project(args.project)
            keeper = GateKeeper(project, ArtifactStore(project))
            for gate in args.gates:
                if gate not in STAGE_NAMES:
                    raise GateError(f"unknown stage {gate!r} (stages: {', '.join(STAGE_NAMES)})")
                keeper.approve(gate)
                print(f"approved {gate}")
            return 0
        result = pipeline.run(
            args.project,
            until=args.until,
            auto=args.auto,
            approve=args.approve,
            approver=_interactive_approver(),
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
