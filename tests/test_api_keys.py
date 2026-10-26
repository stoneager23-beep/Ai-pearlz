"""Key format checks, masking, redaction and command-line key resolution. No network calls."""

import os
import sys

import pytest

from src.utils.api_keys import (
    REDACTED_KEY,
    ApiKeyError,
    KeyFormatProblem,
    check_key_format,
    interactive_prompt,
    mask_secret,
    redact_api_keys,
    resolve_cli_api_key,
)

LEGACY_SHAPED_KEY = "sk-" + "a1B2c3D4e5" * 4 + "f6G7h8I9j0K"


def test_project_and_legacy_shaped_keys_pass(fake_key):
    assert check_key_format(fake_key) is None
    assert check_key_format(LEGACY_SHAPED_KEY) is None


def test_surrounding_whitespace_from_copy_paste_is_tolerated(fake_key):
    assert check_key_format(f"  {fake_key}\n") is None


@pytest.mark.parametrize(
    ("pasted", "problem"),
    [
        ("", KeyFormatProblem.EMPTY),
        ("   \n", KeyFormatProblem.EMPTY),
        ("pk-live-0123456789abcdef0123456789abcdef01234567", KeyFormatProblem.WRONG_PREFIX),
        ("sk-admin-0123456789abcdef0123456789abcdef0123", KeyFormatProblem.ADMIN_KEY),
        ("sk-proj-0123456789abcdef 0123456789abcdef0123", KeyFormatProblem.CONTAINS_WHITESPACE),
        ("sk-proj-0123456789abcdef!0123456789abcdef0123", KeyFormatProblem.UNEXPECTED_CHARACTERS),
        ("sk-proj-0123456789", KeyFormatProblem.TOO_SHORT),
    ],
)
def test_malformed_keys_are_rejected_with_a_specific_reason(pasted, problem):
    assert check_key_format(pasted) is problem


def test_every_problem_has_a_human_message():
    for problem in KeyFormatProblem:
        assert problem.value.endswith(".")
        assert "error" not in problem.value.lower()


def test_mask_shows_only_the_public_prefix(fake_key):
    masked = mask_secret(fake_key)

    assert masked.startswith("sk-")
    assert fake_key[3:10] not in masked


def test_redaction_removes_full_and_partly_masked_keys(fake_key):
    text = (
        f"auth with {fake_key} failed: Incorrect API key provided: "
        "sk-proj-****************************abcd."
    )

    redacted = redact_api_keys(text)

    assert fake_key not in redacted
    assert "abcd" not in redacted
    assert redacted.count(REDACTED_KEY) == 2


def test_redaction_leaves_ordinary_words_alone():
    text = "task-management and desk-booking are not keys; neither is sk-12."

    assert redact_api_keys(text) == text


def test_environment_key_is_used_first(monkeypatch, tmp_path, fake_key):
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={LEGACY_SHAPED_KEY}\n", encoding="utf-8")

    assert resolve_cli_api_key(env_file, prompt=None) == fake_key


def test_env_file_key_is_used_without_touching_os_environ(monkeypatch, tmp_path, fake_key):
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={fake_key}\n", encoding="utf-8")

    assert resolve_cli_api_key(env_file, prompt=None) == fake_key
    assert "OPENAI_API_KEY" not in os.environ


def test_prompt_is_used_when_no_key_is_configured(fake_key):
    asked = []

    def fake_prompt(message: str) -> str:
        asked.append(message)
        return f"{fake_key}\n"

    assert resolve_cli_api_key(None, prompt=fake_prompt) == fake_key
    assert asked == ["OpenAI API key (input hidden): "]


@pytest.mark.parametrize(
    ("stdin_is_terminal", "stdout_is_terminal", "expected_prompt"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_prompt_only_when_both_streams_are_terminals(
    monkeypatch, stdin_is_terminal, stdout_is_terminal, expected_prompt
):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin_is_terminal, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout_is_terminal, raising=False)

    assert (interactive_prompt() is not None) is expected_prompt


def test_missing_key_without_a_terminal_fails_clearly():
    with pytest.raises(ApiKeyError, match="OPENAI_API_KEY is not set"):
        resolve_cli_api_key(None, prompt=None)


def test_malformed_configured_key_fails_with_the_format_reason(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-key")

    with pytest.raises(ApiKeyError, match="start with"):
        resolve_cli_api_key(None, prompt=None)
