"""Fixture that puts fake ``gemini`` / ``claude`` / ``codex`` executables on PATH."""

from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

FAKE_CLI_SCRIPT = Path(__file__).resolve().parent / "fake_cli.py"
BINARIES = ("gemini", "claude", "codex")


@dataclass
class Call:
    argv: list[str]
    cwd: Path
    cwd_entries: list[str]
    stdin: str


class FakeClis:
    """Queue canned replies per CLI and inspect how each CLI was invoked."""

    def __init__(self, root: Path, bin_dir: Path) -> None:
        self.root = root
        self.bin_dir = bin_dir

    def uninstall(self, binary: str) -> None:
        """Remove a CLI from PATH, as if it were not installed."""
        for wrapper in self.bin_dir.glob(f"{binary}*"):
            wrapper.unlink()

    def _file(self, binary: str) -> Path:
        return self.root / f"{binary}.json"

    def _state(self, binary: str) -> dict[str, Any]:
        return json.loads(self._file(binary).read_text(encoding="utf-8"))

    def _queue(self, binary: str, replies: list[dict[str, Any]]) -> None:
        state = self._state(binary)
        state["replies"] += replies
        self._file(binary).write_text(json.dumps(state), encoding="utf-8")

    def reply(self, binary: str, *texts: str) -> None:
        """Queue answers; each is wrapped in the CLI's normal output envelope."""
        self._queue(binary, [{"kind": "text", "text": t} for t in texts])

    def raw(self, binary: str, stdout: str, *, stderr: str = "", exit_code: int = 0) -> None:
        """Queue a reply emitted verbatim (malformed envelopes, rate limits, crashes)."""
        self._queue(
            binary, [{"kind": "raw", "stdout": stdout, "stderr": stderr, "exit": exit_code}]
        )

    def fail(self, binary: str, stderr: str, exit_code: int = 1) -> None:
        self._queue(binary, [{"kind": "fail", "stderr": stderr, "exit": exit_code}])

    def hang(self, binary: str) -> None:
        """Queue a reply that blocks until :meth:`release`, so the run calling it stays in progress."""
        self._queue(binary, [{"kind": "hang"}])

    @property
    def hanging(self) -> bool:
        """Whether a ``hang`` reply has been reached (some run is now blocked in that CLI)."""
        return (self.root / "hanging").exists()

    def release(self) -> None:
        """Let every blocked ``hang`` reply return (as a failure)."""
        (self.root / "release").write_text("", encoding="utf-8")

    def calls(self, binary: str) -> list[Call]:
        return [
            Call(c["argv"], Path(c["cwd"]), c["cwd_entries"], c["stdin"])
            for c in self._state(binary)["calls"]
        ]


@pytest.fixture
def fake_clis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClis:
    state_dir = tmp_path / "fake-cli-state"
    bin_dir = tmp_path / "fake-cli-bin"
    state_dir.mkdir()
    bin_dir.mkdir()
    for binary in BINARIES:
        (state_dir / f"{binary}.json").write_text(
            json.dumps({"replies": [], "calls": []}), encoding="utf-8"
        )
        if os.name == "nt":
            wrapper = bin_dir / f"{binary}.cmd"
            wrapper.write_text(
                f'@"{sys.executable}" -I -S "{FAKE_CLI_SCRIPT}" {binary} %*\n', encoding="utf-8"
            )
        else:
            wrapper = bin_dir / binary
            wrapper.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" -I -S "{FAKE_CLI_SCRIPT}" {binary} "$@"\n',
                encoding="utf-8",
            )
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    # PATH holds only the fakes (plus System32 for cmd.exe on Windows), so a test can never reach
    # a real gemini/claude/codex installed on the machine, not even by uninstalling a fake.
    system = [str(Path(os.environ["SYSTEMROOT"]) / "System32")] if os.name == "nt" else []
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), *system]))
    monkeypatch.setenv("VIDPIPE_FAKE_CLI_DIR", str(state_dir))
    return FakeClis(state_dir, bin_dir)
