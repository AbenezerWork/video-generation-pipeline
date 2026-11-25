"""Seam 2 for the CLI text adapters: each runs the text conformance suite against a fake
executable on PATH (the real CLIs run the same suite under the ``integration`` marker through
``test_providers.py``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from tests.cli_text_fixtures import FakeClis
from tests.conformance import suites
from vidpipe.contracts import ProviderKind, TextProvider
from vidpipe.registry import default_registry
from vidpipe.text import InvalidOutput, ProviderUnavailable, RateLimited, TextProviderError, ask

ADAPTERS = {"gemini-cli": "gemini", "claude-cli": "claude", "codex-cli": "codex"}


def make(name: str) -> TextProvider:
    provider = default_registry().create(ProviderKind.TEXT, name)
    assert isinstance(provider, TextProvider)
    return provider


class Echo(BaseModel):
    word: str
    count: int = Field(ge=0)


GOOD = '{"word": "hello", "count": 2}'


def ask_echo(adapter: str) -> Echo:
    return ask(make(adapter), "Return a word and a count.", Echo)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_cli_adapter_passes_the_text_conformance_suite(
    adapter: str, fake_clis: FakeClis, tmp_path: Path
) -> None:
    fake_clis.reply(ADAPTERS[adapter], '{"word": "hello", "count": 2}')

    suites.check_text(make(adapter), tmp_path)


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(GOOD, id="bare"),
        pytest.param(f"```json\n{GOOD}\n```", id="fenced"),
        pytest.param(f"Sure! Here is the JSON you asked for:\n\n{GOOD}\n\nAnything else?", id="prose"),
        pytest.param('Note {not json} first. ' + GOOD, id="stray-braces"),
    ],
)
def test_json_is_extracted_from_the_reply(adapter: str, reply: str, fake_clis: FakeClis) -> None:
    fake_clis.reply(ADAPTERS[adapter], reply)

    assert ask_echo(adapter) == Echo(word="hello", count=2)
    assert len(fake_clis.calls(ADAPTERS[adapter])) == 1


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_malformed_output_is_re_prompted_with_the_error_up_to_twice(
    adapter: str, fake_clis: FakeClis
) -> None:
    binary = ADAPTERS[adapter]
    fake_clis.reply(binary, "I cannot do that.", '{"word": "hello", "count": -5}', GOOD)

    assert ask_echo(adapter) == Echo(word="hello", count=2)

    calls = fake_clis.calls(binary)
    assert len(calls) == 3
    assert "no JSON object" in calls[1].stdin  # the error is fed back...
    assert "I cannot do that." in calls[1].stdin  # ...with the rejected reply
    assert "greater than or equal to 0" in calls[2].stdin  # validation errors too


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_gives_up_after_two_re_prompts(adapter: str, fake_clis: FakeClis) -> None:
    binary = ADAPTERS[adapter]
    fake_clis.reply(binary, "nope", "still nope", "nope again", GOOD)

    with pytest.raises(InvalidOutput):
        ask_echo(adapter)

    assert len(fake_clis.calls(binary)) == 3  # the fourth reply is never asked for


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_a_semantic_check_failure_is_re_prompted_too(adapter: str, fake_clis: FakeClis) -> None:
    binary = ADAPTERS[adapter]
    fake_clis.reply(binary, '{"word": "bad", "count": 1}', GOOD)

    def check(echo: Echo) -> None:
        if echo.word == "bad":
            raise ValueError("the word 'bad' is not allowed")

    assert ask(make(adapter), "p", Echo, check) == Echo(word="hello", count=2)
    assert "the word 'bad' is not allowed" in fake_clis.calls(binary)[1].stdin


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_rate_limit_and_crashes_are_distinguished_and_not_retried(
    adapter: str, fake_clis: FakeClis
) -> None:
    binary = ADAPTERS[adapter]
    fake_clis.fail(binary, "Error 429: RESOURCE_EXHAUSTED, quota exceeded")
    fake_clis.fail(binary, "segmentation fault", exit_code=139)

    with pytest.raises(RateLimited):
        ask_echo(adapter)
    with pytest.raises(TextProviderError) as crash:
        ask_echo(adapter)

    assert not isinstance(crash.value, RateLimited)
    assert len(fake_clis.calls(binary)) == 2  # one call each, no re-prompt


def test_claude_error_envelope_is_reported(fake_clis: FakeClis) -> None:
    fake_clis.raw(
        "claude",
        json.dumps({"type": "result", "is_error": True, "result": "You've hit your usage limit"}),
        exit_code=1,
    )

    with pytest.raises(RateLimited, match="usage limit"):
        ask_echo("claude-cli")


def test_missing_executable_is_an_unavailable_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ProviderUnavailable, match="gemini"):
        ask_echo("gemini-cli")


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_cli_runs_in_an_empty_temp_directory_with_tools_disabled(
    adapter: str, fake_clis: FakeClis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = ADAPTERS[adapter]
    project = tmp_path / "project"
    project.mkdir()
    (project / "secret.txt").write_text("hands off")
    monkeypatch.chdir(project)
    fake_clis.reply(binary, GOOD)

    ask_echo(adapter)

    (call,) = fake_clis.calls(binary)
    assert call.cwd_entries == []  # an empty directory...
    assert not call.cwd.is_relative_to(project)  # ...that is not the user's
    assert not call.cwd.exists()  # ...and it is deleted afterwards
    flags = call.argv
    if binary == "claude":
        assert flags[flags.index("--tools") + 1] == ""  # "" = no built-in tools
        assert "--safe-mode" in flags
    elif binary == "gemini":
        assert flags[flags.index("--approval-mode") + 1] == "plan"
        assert "--policy" in flags  # the deny-all-tools policy (a temp file, gone by now)
    else:
        assert flags[flags.index("--sandbox") + 1] == "read-only"
        assert "shell_tool" in flags


def test_model_and_command_options_are_passed_through(
    fake_clis: FakeClis, tmp_path: Path
) -> None:
    fake_clis.reply("claude", GOOD)
    provider = default_registry().create(ProviderKind.TEXT, "claude-cli", model="opus")
    assert isinstance(provider, TextProvider)

    ask(provider, "p", Echo)

    argv = fake_clis.calls("claude")[0].argv
    assert argv[argv.index("--model") + 1] == "opus"
