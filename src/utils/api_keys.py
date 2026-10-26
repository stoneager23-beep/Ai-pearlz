"""OpenAI API key handling shared by the command-line tools and the Streamlit gate.

Nothing here makes a network call. The module answers four questions:

- Is a pasted string plausibly an OpenAI key? (checked before we spend a request on it)
- What masked form of a key is safe to print?
- How do we strip keys out of any text before it is logged?
- Where does a command-line tool get its key from?

The key is never stored in the shared settings object: settings are printed, logged and
shared between Streamlit sessions, while a key belongs to one person.
"""

import os
import re
import sys
from collections.abc import Callable
from enum import StrEnum
from getpass import getpass
from pathlib import Path

from dotenv import dotenv_values

API_KEY_ENV_VAR = "OPENAI_API_KEY"
REDACTED_KEY = "sk-[REDACTED]"

_KEY_PREFIX = "sk-"
_ADMIN_KEY_PREFIX = "sk-admin-"
# The shortest current OpenAI key format is 51 characters; anything far shorter was cut off.
_MIN_KEY_LENGTH = 40
_KEY_ALPHABET = re.compile(r"^[A-Za-z0-9_\-]+$")
_VISIBLE_PREFIX_LENGTH = len(_KEY_PREFIX)

# Matches full keys and the partly masked form OpenAI echoes back in 401 errors
# ("sk-proj-****abcd"). The look-behind stops it matching inside words like "task-list".
_KEY_IN_TEXT = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-*]{8,}")


class KeyFormatProblem(StrEnum):
    """Reasons a pasted key is rejected before any network call. Values are user-facing."""

    EMPTY = "Paste your OpenAI API key to continue."
    WRONG_PREFIX = 'That doesn\'t look like an OpenAI API key. Keys start with "sk-".'
    ADMIN_KEY = "That is an admin key, which cannot call models. Use a project API key instead."
    CONTAINS_WHITESPACE = "The key contains spaces or line breaks. Paste it again as one line."
    UNEXPECTED_CHARACTERS = (
        "The key contains characters OpenAI keys never use. Check it was copied in full."
    )
    TOO_SHORT = "The key looks too short. It may have been cut off while copying."


class ApiKeyError(Exception):
    """Raised when a command-line tool cannot obtain a usable key. The message is user-facing."""


def check_key_format(key: str) -> KeyFormatProblem | None:
    """Return the first format problem with `key`, or None if it is plausibly an OpenAI key.

    Surrounding whitespace is ignored because copy-paste often adds a trailing newline.
    """
    candidate = key.strip()
    if not candidate:
        return KeyFormatProblem.EMPTY
    if not candidate.startswith(_KEY_PREFIX):
        return KeyFormatProblem.WRONG_PREFIX
    if candidate.startswith(_ADMIN_KEY_PREFIX):
        return KeyFormatProblem.ADMIN_KEY
    if any(character.isspace() for character in candidate):
        return KeyFormatProblem.CONTAINS_WHITESPACE
    if not _KEY_ALPHABET.match(candidate):
        return KeyFormatProblem.UNEXPECTED_CHARACTERS
    if len(candidate) < _MIN_KEY_LENGTH:
        return KeyFormatProblem.TOO_SHORT
    return None


def mask_secret(secret: str) -> str:
    """Return a printable stand-in that shows only the public "sk-" prefix."""
    return f"{secret[:_VISIBLE_PREFIX_LENGTH]}********"


def redact_api_keys(text: str) -> str:
    """Replace anything that looks like an OpenAI key (full or partly masked) in `text`."""
    return _KEY_IN_TEXT.sub(REDACTED_KEY, text)


def interactive_prompt() -> Callable[[str], str] | None:
    """Return a hidden-input prompt when a person is at the terminal, otherwise None.

    Both streams must be terminals: on Windows, stdin redirected from NUL still reports
    isatty() == True, and getpass would then wait forever on a console nobody is watching.
    """
    return getpass if sys.stdin.isatty() and sys.stdout.isatty() else None


def resolve_cli_api_key(
    env_file: Path | None,
    prompt: Callable[[str], str] | None,
) -> str:
    """Find the key for a command-line tool: environment, then `.env`, then `prompt`.

    `prompt` is only used when no key is configured; pass None for unattended runs, which then
    fail with one clear message instead of hanging on input. The `.env` file is read without
    copying it into `os.environ`, so other code in the process cannot pick the key up by accident.
    """
    key = os.environ.get(API_KEY_ENV_VAR) or _read_key_from_env_file(env_file)
    if not key:
        if prompt is None:
            raise ApiKeyError(
                f"{API_KEY_ENV_VAR} is not set. Add it to .env, or run this command in a "
                "terminal to enter it with hidden input."
            )
        key = prompt("OpenAI API key (input hidden): ")

    problem = check_key_format(key)
    if problem is not None:
        raise ApiKeyError(problem.value)
    return key.strip()


def _read_key_from_env_file(env_file: Path | None) -> str | None:
    if env_file is None or not env_file.is_file():
        return None
    return dotenv_values(env_file).get(API_KEY_ENV_VAR)
