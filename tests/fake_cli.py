"""A fake ``gemini`` / ``claude`` / ``codex`` executable for testing the CLI text adapters.

Run as ``python fake_cli.py <flavor> <the real CLI's argv...>`` from a tiny wrapper placed on PATH
(see ``tests/cli_text_fixtures.py``). Replies come from a queue in ``$VIDPIPE_FAKE_CLI_DIR``,
one per invocation, and every invocation (argv, cwd, what was in the cwd, stdin) is logged there so
tests can check how the adapter ran the CLI. Canned replies are wrapped in the output envelope each
real CLI uses; ``raw`` and ``fail`` replies are emitted verbatim to simulate malformed output,
rate limits and crashes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast


def _envelope(flavor: str, text: str) -> str:
    if flavor == "claude":
        return json.dumps(
            {"type": "result", "subtype": "success", "is_error": False, "result": text}
        )
    if flavor == "gemini":
        return json.dumps({"response": text, "stats": {"models": {}}})
    return text  # codex prints the final message as plain text


def main() -> int:
    flavor, args = sys.argv[1], sys.argv[2:]
    state_file = Path(os.environ["VIDPIPE_FAKE_CLI_DIR"]) / f"{flavor}.json"
    state: dict[str, Any] = json.loads(state_file.read_text(encoding="utf-8"))
    cwd = Path.cwd()
    # The adapters send UTF-8 (Amharic prompts); a Windows pipe would otherwise read cp1252.
    cast(Any, sys.stdin).reconfigure(encoding="utf-8")
    state["calls"].append(
        {
            "argv": args,
            "cwd": str(cwd),
            "cwd_entries": sorted(p.name for p in cwd.iterdir()),
            "stdin": sys.stdin.read(),
        }
    )
    index = len(state["calls"]) - 1
    reply: dict[str, Any] = (
        state["replies"][index]
        if index < len(state["replies"])
        else {"kind": "fail", "stderr": "fake cli: no reply queued", "exit": 99}
    )
    state_file.write_text(json.dumps(state), encoding="utf-8")

    cast(Any, sys.stdout).reconfigure(encoding="utf-8")
    cast(Any, sys.stderr).reconfigure(encoding="utf-8")
    if reply["kind"] == "text":
        if flavor == "codex":
            # `codex exec ... --output-last-message <file>` writes the final message there.
            for flag in ("-o", "--output-last-message"):
                if flag in args:
                    Path(args[args.index(flag) + 1]).write_text(reply["text"], encoding="utf-8")
            print("OpenAI Codex (fake) -- session banner", file=sys.stderr)
        print(_envelope(flavor, reply["text"]))
        return 0
    sys.stdout.write(reply.get("stdout", ""))
    sys.stderr.write(reply.get("stderr", ""))
    return int(reply.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
