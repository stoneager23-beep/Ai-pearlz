""".env.example documents exactly the variables the project reads, with matching defaults."""

from src.config import PROJECT_ROOT, Settings, load_settings
from src.utils.api_keys import API_KEY_ENV_VAR

ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


def _documented_variable_names() -> set[str]:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    return {line.partition("=")[0] for line in lines if line and not line.startswith("#")}


def test_every_setting_and_the_key_are_documented():
    expected = {name.upper() for name in Settings.model_fields} | {API_KEY_ENV_VAR}

    assert _documented_variable_names() == expected


def test_documented_values_are_the_defaults():
    assert load_settings(env_file=ENV_EXAMPLE) == load_settings(env_file=None)
