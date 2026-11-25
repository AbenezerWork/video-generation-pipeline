"""A real ``vidpipe run`` in its own process, held mid-script by a fake CLI's ``hang`` reply."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from tests.cli_text_fixtures import FakeClis


class Writer:
    """A ``vidpipe run`` in its own process, blocked inside the script stage's CLI."""

    def __init__(
        self, project: Path, fake_clis: FakeClis, *, env: dict[str, str] | None = None
    ) -> None:
        self.fake_clis = fake_clis
        fake_clis.hang("gemini")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "vidpipe", "run", str(project), "--until", "script"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **(env or {})},
        )
        deadline = time.monotonic() + 30
        while not fake_clis.hanging:
            assert self.process.poll() is None, "the writer exited before reaching the script"
            assert time.monotonic() < deadline, "the writer never reached the script stage"
            time.sleep(0.05)

    def kill(self) -> None:
        self.process.kill()
        self.process.wait()

    def finish(self) -> None:
        self.fake_clis.release()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.kill()
