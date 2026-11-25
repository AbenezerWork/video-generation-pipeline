"""Run one ``vidpipe`` command with the shared GPU to itself.

``python run_gpu.py [--comfy-url URL] [--lock PATH] -- <vidpipe arguments...>``

Waits for the machine-wide GPU lock (the same OS file lock vidpipe takes per project, from
``filelock``), then for ComfyUI's queue to be empty, then runs the command in this process. The
project's own one-writer lock is taken by vidpipe as usual. Either lock is released by the OS if
this process dies, so a killed run never blocks the next one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from filelock import FileLock, Timeout

from vidpipe.cli import main as vidpipe

DEFAULT_LOCK = Path(os.path.expanduser("~")) / ".t3" / "vidpipe-deps" / "integration-gpu.lock"
POLL_S = 2.0


def _comfy_busy(url: str) -> bool:
    with urllib.request.urlopen(f"{url.rstrip('/')}/queue", timeout=10) as response:
        queue = json.load(response)
    return bool(queue.get("queue_running") or queue.get("queue_pending"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK, help="the GPU lock file")
    parser.add_argument(
        "vidpipe_args", nargs=argparse.REMAINDER, help="-- then the vidpipe arguments"
    )
    args = parser.parse_args(argv)
    command = args.vidpipe_args[1:] if args.vidpipe_args[:1] == ["--"] else args.vidpipe_args
    if not command:
        parser.error("give the vidpipe command after --")

    args.lock.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(
        args.lock, poll_interval=POLL_S, fallback_to_soft=False, preserve_lock_file=True
    )
    try:
        lock.acquire(timeout=0)
    except Timeout:
        print(f"waiting for the GPU lock {args.lock} ...", file=sys.stderr, flush=True)
        lock.acquire()
    try:
        while _comfy_busy(args.comfy_url):
            time.sleep(POLL_S)
        return vidpipe(command)
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
