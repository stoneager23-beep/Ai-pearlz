"""Settings are environment-driven, validated, and fail with one readable message."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import PROJECT_ROOT, ConfigError, load_settings, main


def test_defaults_load_without_any_configuration():
    settings = load_settings(env_file=None)

    assert settings.openai_chat_model == "gpt-4.1-mini"
    assert settings.llm_temperature == 0.0
    assert settings.chunk_overlap < settings.chunk_size


def test_environment_variables_override_defaults(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "500")
    monkeypatch.setenv("RETRIEVAL_K", "8")

    settings = load_settings(env_file=None)

    assert settings.chunk_size == 500
    assert settings.retrieval_k == 8


def test_env_file_is_read(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("COLLECTION_NAME=test_kb\n", encoding="utf-8")

    assert load_settings(env_file=env_file).collection_name == "test_kb"


def test_comma_separated_model_list_is_parsed(monkeypatch):
    monkeypatch.setenv("OPENAI_CHAT_MODELS", " gpt-4o , gpt-4.1-mini,")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-4o")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-4o")

    settings = load_settings(env_file=None)

    assert settings.openai_chat_models == ("gpt-4o", "gpt-4.1-mini")
    assert [option.label for option in settings.chat_model_options()] == [
        "GPT-4o",
        "GPT-4.1 mini",
    ]


def test_overlap_not_smaller_than_size_is_rejected(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "800")
    monkeypatch.setenv("CHUNK_OVERLAP", "800")

    with pytest.raises(ConfigError, match=r"CHUNK_OVERLAP \(800\) must be smaller than CHUNK_SIZE"):
        load_settings(env_file=None)


def test_unknown_chat_model_is_rejected_with_the_allowed_list(monkeypatch):
    monkeypatch.setenv("OPENAI_CHAT_MODELS", "gpt-4o,made-up-model")

    with pytest.raises(ConfigError, match=r"made-up-model; choose from: gpt-4.1-mini"):
        load_settings(env_file=None)


def test_default_model_must_be_offered(monkeypatch):
    monkeypatch.setenv("OPENAI_CHAT_MODELS", "gpt-4o")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-4o")

    with pytest.raises(ConfigError, match=r"OPENAI_CHAT_MODEL \(gpt-4.1-mini\) must be one of"):
        load_settings(env_file=None)


def test_high_temperature_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.9")

    with pytest.raises(ConfigError, match="LLM_TEMPERATURE"):
        load_settings(env_file=None)


def test_non_numeric_value_names_the_variable(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "large")

    with pytest.raises(ConfigError) as raised:
        load_settings(env_file=None)

    assert "CHUNK_SIZE" in str(raised.value)
    assert "Traceback" not in str(raised.value)


def test_relative_paths_are_resolved_from_project_root(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE_DIR", "data/other_store")

    settings = load_settings(env_file=None)

    assert settings.vector_store_dir == PROJECT_ROOT / "data" / "other_store"


def test_log_level_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert load_settings(env_file=None).log_level == "DEBUG"


def test_settings_are_immutable():
    settings = load_settings(env_file=None)

    with pytest.raises(ValidationError):
        settings.retrieval_k = 99


def test_settings_never_hold_the_api_key(monkeypatch, fake_key):
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)

    settings = load_settings(env_file=None)

    assert fake_key not in repr(settings)
    assert fake_key not in str(settings.model_dump())


def test_smoke_check_prints_configuration_with_key_masked(monkeypatch, capsys, fake_key):
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)

    exit_code = main(env_file=None)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "CHUNK_SIZE" in output
    assert "sk-********" in output
    assert fake_key not in output


def test_smoke_check_without_key_gives_one_clear_error(capsys):
    exit_code = main(env_file=None)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.strip() == (
        "OPENAI_API_KEY is not set. Add it to .env, or run this command in a terminal "
        "to enter it with hidden input."
    )


def test_smoke_check_reports_invalid_configuration(monkeypatch, capsys, fake_key):
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)
    monkeypatch.setenv("CHUNK_SIZE", "800")
    monkeypatch.setenv("CHUNK_OVERLAP", "5000")

    exit_code = main(env_file=Path("does-not-exist.env"))

    assert exit_code == 1
    assert "CHUNK_OVERLAP (5000) must be smaller than CHUNK_SIZE (800)" in capsys.readouterr().err


def test_judge_model_must_be_offered(monkeypatch):
    monkeypatch.setenv("OPENAI_CHAT_MODELS", "gpt-4.1-mini")

    with pytest.raises(ConfigError, match=r"EVAL_JUDGE_MODEL \(gpt-4\.1\) must be one of"):
        load_settings(env_file=None)
