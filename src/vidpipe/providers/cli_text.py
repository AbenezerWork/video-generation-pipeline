"""Text providers that drive a vendor CLI as a subprocess: Gemini CLI, Claude Code and Codex.

Every adapter runs its CLI

* non-interactively, with the prompt on stdin and machine-readable output;
* with agent tools disabled as far as that CLI allows (see each ``build_command``);
* in a fresh, empty temporary directory, so a misbehaving agent has nothing of the user's to touch;

then extracts the JSON object from the reply and validates it against the request. A reply that is
not valid JSON, or that the request's validator rejects, is sent back to the model with the error:
up to :attr:`CliTextProvider.max_reprompts` (2) re-prompts before the adapter gives up.

Options (``options:`` in ``vidpipe.yaml``): ``model`` (passed to the CLI), ``timeout_s``
(per call, default 300) and ``command`` (executable name or path, default the CLI's usual name).
Check each vendor's current terms for automated use of their CLI before relying on this.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from abc import abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from vidpipe.contracts import TextCapabilities, TextProvider, TextRequest, TextResponse
from vidpipe.registry import register
from vidpipe.text import (
    InvalidOutput,
    ProviderUnavailable,
    RateLimited,
    TextProviderError,
    extract_json,
)

_RATE_LIMIT = re.compile(
    r"\b429\b|rate[ _-]?limit|quota|resource[ _]exhausted|usage limit|too many requests|"
    r"overloaded|capacity",
    re.IGNORECASE,
)
_ECHO_LIMIT = 2000  # characters of a rejected answer echoed back to the model


def _tail(text: str, limit: int = 400) -> str:
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-limit:]


class CliTextProvider(TextProvider):
    #: The CLI's usual executable name.
    binary: ClassVar[str]
    max_reprompts: ClassVar[int] = 2
    capabilities = TextCapabilities(structured_output=True)

    def __init__(
        self,
        *,
        model: str | None = None,
        timeout_s: float | None = None,
        command: str | None = None,
        **options: Any,
    ) -> None:
        """``model``: the CLI's model (its own default when unset); ``timeout_s``: seconds per
        call (300 when unset); ``command``: the executable (``binary`` on PATH when unset)."""
        given = {"model": model, "timeout_s": timeout_s, "command": command}
        super().__init__(**{k: v for k, v in given.items() if v is not None}, **options)
        self.model = model
        self.timeout_s = float(300 if timeout_s is None else timeout_s)
        self.command = str(self.binary if command is None else command)

    # ------------------------------------------------------------------ per-CLI details

    @abstractmethod
    def build_command(self, exe: str, scratch: Path) -> list[str]:
        """The argv for one non-interactive call (prompt arrives on stdin).

        ``scratch`` is a private directory *outside* the process's working directory, for any
        file the CLI needs (a policy, an output file).
        """

    @abstractmethod
    def read_reply(self, completed: subprocess.CompletedProcess[str], scratch: Path) -> str:
        """The model's text from a call that exited 0. Raise :class:`TextProviderError` if the
        CLI reported an error in its output."""

    # ------------------------------------------------------------------------ the call

    def complete(self, request: TextRequest) -> TextResponse:
        prompt = self._prompt(request)
        problem = ""
        for _ in range(1 + self.max_reprompts):
            reply = self._call(prompt)
            try:
                data = extract_json(reply)
                if request.validator is not None:
                    request.validator(data)
            except (InvalidOutput, ValueError) as exc:
                problem = str(exc)
                prompt = self._reprompt(request, reply, problem)
                continue
            return TextResponse(data=data)
        raise InvalidOutput(
            f"{self.name}: no valid answer after {1 + self.max_reprompts} attempts "
            f"(last problem: {_tail(problem)})"
        )

    def _prompt(self, request: TextRequest) -> str:
        return (
            f"{request.prompt}\n\n"
            "Reply with a single JSON object that matches this JSON Schema, and nothing else "
            "(no commentary, no code fence). Do not use any tools, run commands or read files.\n\n"
            f"JSON Schema:\n{json.dumps(request.json_schema, indent=2)}\n"
        )

    def _reprompt(self, request: TextRequest, reply: str, problem: str) -> str:
        return (
            f"{self._prompt(request)}\n"
            f"Your previous reply was rejected: {problem}\n"
            f"Your previous reply was:\n{reply[:_ECHO_LIMIT]}\n\n"
            "Reply again with only the corrected JSON object."
        )

    def _call(self, prompt: str) -> str:
        exe = shutil.which(self.command)
        if exe is None:
            raise ProviderUnavailable(f"{self.name}: executable {self.command!r} not found on PATH")
        with tempfile.TemporaryDirectory(prefix="vidpipe-text-") as tmp:
            work = Path(tmp) / "work"  # the (empty) working directory of the CLI
            scratch = Path(tmp) / "scratch"
            work.mkdir()
            scratch.mkdir()
            try:
                completed = subprocess.run(
                    self.build_command(exe, scratch),
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=work,
                    timeout=self.timeout_s,
                    env={**os.environ, "NO_COLOR": "1"},
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise ProviderUnavailable(
                    f"{self.name}: timed out after {self.timeout_s:g}s"
                ) from None
            except OSError as exc:
                raise ProviderUnavailable(f"{self.name}: cannot run {exe!r}: {exc}") from exc
            if completed.returncode != 0:
                self._raise_failure(completed)
            reply = self.read_reply(completed, scratch)
        if not reply.strip():
            raise InvalidOutput("the reply was empty")
        return reply

    def _raise_failure(self, completed: subprocess.CompletedProcess[str]) -> None:
        detail = _tail(completed.stderr) or _tail(completed.stdout)
        self._raise_for_text(f"exited with status {completed.returncode}: {detail}", detail)

    def _raise_for_text(self, message: str, haystack: str) -> None:
        error = RateLimited if _RATE_LIMIT.search(haystack) else TextProviderError
        raise error(f"{self.name}: {message}")

    def _json_envelope(self, completed: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
        try:
            value = json.loads(completed.stdout)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None  # pyright: ignore[reportUnknownVariableType]


# --------------------------------------------------------------------------------------- Gemini

_GEMINI_DENY_ALL_TOOLS = """\
# vidpipe: text generation never needs tools, so deny every one of them.
[[rule]]
toolName = "*"
decision = "deny"
priority = 999
denyMessage = "vidpipe disables all tools for text generation"
"""


@register
class GeminiCliText(CliTextProvider):
    """``gemini -p ... -o json``: plan mode plus a catch-all policy rule that denies every tool."""

    name = "gemini-cli"
    binary = "gemini"

    def build_command(self, exe: str, scratch: Path) -> list[str]:
        policy = scratch / "deny-all-tools.toml"
        policy.write_text(_GEMINI_DENY_ALL_TOOLS, encoding="utf-8")
        command = [
            exe,
            "-p",
            "Answer the request given on stdin.",  # appended to the stdin prompt
            "-o",
            "json",
            "--approval-mode",
            "plan",  # read-only mode; the policy below denies even the read-only tools
            "--policy",
            str(policy),
            "--skip-trust",  # an empty temp directory is not a trusted workspace
        ]
        return [*command, "-m", self.model] if self.model else command

    def read_reply(self, completed: subprocess.CompletedProcess[str], scratch: Path) -> str:
        envelope = self._json_envelope(completed)
        if envelope is None:
            return completed.stdout  # tolerate plain text
        if envelope.get("error"):
            self._raise_for_text(f"reported an error: {envelope['error']}", str(envelope["error"]))
        return str(envelope.get("response", ""))


# --------------------------------------------------------------------------------------- Claude


@register
class ClaudeCliText(CliTextProvider):
    """``claude -p --output-format json --tools ""``: no built-in tools, no MCP, no settings."""

    name = "claude-cli"
    binary = "claude"

    def build_command(self, exe: str, scratch: Path) -> list[str]:
        command = [
            exe,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "",  # "" = no built-in tools
            "--safe-mode",  # no CLAUDE.md, skills, plugins, hooks, MCP servers or custom commands
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        return [*command, "--model", self.model] if self.model else command

    def read_reply(self, completed: subprocess.CompletedProcess[str], scratch: Path) -> str:
        envelope = self._json_envelope(completed)
        if envelope is None:
            return completed.stdout
        if envelope.get("is_error"):
            message = str(envelope.get("result", ""))
            self._raise_for_text(f"reported an error: {_tail(message)}", message)
        return str(envelope.get("result", ""))

    def _raise_failure(self, completed: subprocess.CompletedProcess[str]) -> None:
        # On errors Claude Code still prints its JSON envelope to stdout; the message is in it.
        envelope = self._json_envelope(completed)
        if envelope is not None and envelope.get("result"):
            message = str(envelope["result"])
            self._raise_for_text(f"reported an error: {_tail(message)}", message)
        super()._raise_failure(completed)


# ---------------------------------------------------------------------------------------- Codex


@register
class CodexCliText(CliTextProvider):
    """``codex exec``: read-only sandbox, shell and other tools disabled, nothing persisted."""

    name = "codex-cli"
    binary = "codex"

    def build_command(self, exe: str, scratch: Path) -> list[str]:
        command = [
            exe,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",  # no session files
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-last-message",
            str(scratch / "last-message.txt"),
        ]
        for feature in ("shell_tool", "unified_exec", "apps", "browser_use", "computer_use"):
            command += ["--disable", feature]
        if self.model:
            command += ["-m", self.model]
        return [*command, "-"]  # "-": read the prompt from stdin

    def read_reply(self, completed: subprocess.CompletedProcess[str], scratch: Path) -> str:
        last_message = scratch / "last-message.txt"
        if last_message.is_file():
            return last_message.read_text(encoding="utf-8", errors="replace")
        return completed.stdout
