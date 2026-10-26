"""Shared test fixtures.

Every test runs with the configuration variables and the API key removed from the environment,
so a developer's real `.env` or shell variables can never change a result or leak into output.
Tests that need settings pass `env_file=None` or a temporary file explicitly.
"""

import pytest

from src.config import Settings, get_settings
from src.utils.api_keys import API_KEY_ENV_VAR

# A well-formed but fake key: long enough to pass the format check, never valid at OpenAI.
FAKE_KEY = "sk-proj-" + "TestOnlyNotARealKey0123456789" * 3


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    get_settings.cache_clear()


@pytest.fixture
def fake_key() -> str:
    return FAKE_KEY
