"""``vidpipe`` command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, cast

from vidpipe import pipeline
from vidpipe.assembly import AssemblyError
from vidpipe.project import Project, ProjectError
from vidpipe.stages import STAGE_NAMES, StageError
from vidpipe.translate import report_lines


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


def _utf8_output() -> None:
    """Print Unicode (Ge'ez narration, say) whatever the console's code page is.

    A Windows console prints Unicode fine, but redirected output (a pipe, a file) falls back to
    the locale code page (cp1252), which cannot hold Ge'ez and would crash the command with
    ``UnicodeEncodeError``. Files vidpipe writes are always UTF-8, so output is made UTF-8 too.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding.lower().replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            cast(Any, stream).reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
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
            print(f"{record.stage:<14}{record.provider or '-':<26}{status}")
        if any(record.stage == "translation" for record in result.manifest.stages):
            for warning in report_lines(Project(args.project)):
                print(warning, file=sys.stderr)
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
