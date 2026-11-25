"""``vidpipe`` command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vidpipe import pipeline
from vidpipe.assembly import AssemblyError
from vidpipe.project import ProjectError
from vidpipe.stages import STAGE_NAMES, StageError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vidpipe", description="Studio pipeline for short video.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("run", "run the stage graph on a project directory"),
        ("plan", "show the plan and check capabilities; generates nothing"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("project", type=Path, help="project directory (brief.md + vidpipe.yaml)")
        cmd.add_argument("--until", choices=STAGE_NAMES, help="stop after this stage (inclusive)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            the_plan = pipeline.plan(args.project, until=args.until)
            for stage in the_plan.stages:
                print(f"{stage.name:<14}{stage.provider or '-'}")
            for problem in the_plan.problems:
                print(f"error: {problem}", file=sys.stderr)
            return 0 if the_plan.ok else 1
        result = pipeline.run(args.project, until=args.until)
        for record in result.manifest.stages:
            status = "skipped" if record.skipped else f"ran ({record.generated} generated)"
            print(f"{record.stage:<14}{record.provider or '-':<20}{status}")
        return 0
    except pipeline.PlanError as exc:
        for problem in exc.problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    except (ProjectError, StageError, AssemblyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
