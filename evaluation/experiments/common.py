"""Setup shared by the experiment scripts: settings, logging, API key and result files."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.config import DEFAULT_ENV_FILE, Settings, get_settings
from src.utils.api_keys import interactive_prompt, resolve_cli_api_key
from src.utils.logging_setup import configure_logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExperimentContext:
    settings: Settings
    api_key: str


def start_experiment() -> ExperimentContext:
    """Load settings, configure logging and get the API key (environment, .env or prompt).

    Raises ConfigError or ApiKeyError with a readable message if either is missing.
    """
    settings = get_settings()
    configure_logging(settings)
    api_key = resolve_cli_api_key(DEFAULT_ENV_FILE, prompt=interactive_prompt())
    return ExperimentContext(settings=settings, api_key=api_key)


def run_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def write_result(settings: Settings, file_name: str, markdown: str) -> Path:
    """Write a result table to RESULTS_DIR and return its path."""
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    path = settings.results_dir / file_name
    path.write_text(markdown, encoding="utf-8", newline="\n")
    logger.info("Wrote %s", path)
    return path


def markdown_table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)
