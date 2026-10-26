"""An API key logged anywhere, by our code or a library, never reaches stdout, stderr or the file.

Logging is configured inside each test body, not in a fixture: pytest swaps in the `capsys`
stream only while the test body runs, and a handler created earlier would write to a stream
pytest has already closed.
"""

import logging

import pytest

from src.config import load_settings
from src.utils.api_keys import REDACTED_KEY
from src.utils.logging_setup import LOG_FILE_NAME, configure_logging

OUR_HANDLER_PREFIX = "supportpearlz"


def _our_handlers() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger().handlers
        if (handler.get_name() or "").startswith(OUR_HANDLER_PREFIX)
    ]


@pytest.fixture
def log_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    # Recorded so the global flag configure_logging changes is restored afterwards.
    monkeypatch.setattr(logging, "raiseExceptions", logging.raiseExceptions)
    yield tmp_path / LOG_FILE_NAME
    for handler in _our_handlers():
        logging.getLogger().removeHandler(handler)
        handler.close()


def _configure() -> None:
    configure_logging(load_settings(env_file=None))


def _flush() -> None:
    for handler in _our_handlers():
        handler.flush()


def test_key_never_reaches_stdout_or_file(log_file, capsys, fake_key):
    _configure()

    logging.getLogger("src.chains").info("calling model with key=%s", fake_key)
    logging.getLogger("openai").warning("request failed for %s", fake_key)
    try:
        raise RuntimeError(f"upstream rejected {fake_key}")
    except RuntimeError:
        logging.getLogger("src.app").exception("model call failed")
    _flush()

    console_output = capsys.readouterr().out
    file_output = log_file.read_text(encoding="utf-8")
    assert fake_key not in console_output
    assert fake_key not in file_output
    # The console shows the two messages; the file also keeps the (redacted) traceback.
    assert console_output.count(REDACTED_KEY) == 2
    assert file_output.count(REDACTED_KEY) == 3
    assert "RuntimeError" in file_output


def test_partly_masked_key_from_openai_errors_is_redacted(log_file, capsys):
    _configure()

    logging.getLogger("src.app").error(
        "401: Incorrect API key provided: sk-proj-**********************wxyz"
    )
    _flush()

    assert "wxyz" not in log_file.read_text(encoding="utf-8")
    assert "wxyz" not in capsys.readouterr().out


class _FailingHandler(logging.Handler):
    """Fails the way real handlers do (disk full, closed stream): it reports via handleError."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            raise OSError("disk full")
        except OSError:
            self.handleError(record)


def test_failing_handler_does_not_print_the_raw_exception(log_file, capsys, fake_key):
    _configure()
    failing = _FailingHandler()
    logging.getLogger().addHandler(failing)
    try:
        try:
            raise RuntimeError(f"upstream rejected {fake_key}")
        except RuntimeError:
            logging.getLogger("src.app").exception("model call failed")
    finally:
        logging.getLogger().removeHandler(failing)

    captured = capsys.readouterr()
    assert fake_key not in captured.err
    assert fake_key not in captured.out


def test_reconfiguring_does_not_duplicate_handlers(log_file):
    _configure()
    _configure()
    _configure()

    assert len(_our_handlers()) == 2


def test_log_lines_are_timestamped(log_file):
    _configure()

    logging.getLogger("src.app").info("hello")
    _flush()

    line = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    timestamp, level, logger_name, message = line.split(" | ")
    assert len(timestamp) >= len("2026-01-01T00:00:00")
    assert (level.strip(), logger_name, message) == ("INFO", "src.app", "hello")


def test_console_never_shows_a_traceback_but_the_file_keeps_it(log_file, capsys):
    _configure()

    try:
        raise RuntimeError("connection refused")
    except RuntimeError:
        logging.getLogger("src.app").warning("turn failed", exc_info=True)
    _flush()

    console_output = capsys.readouterr().out
    assert "turn failed" in console_output
    assert "Traceback" not in console_output
    assert "Traceback" in log_file.read_text(encoding="utf-8")


def test_console_level_can_be_raised_without_affecting_the_file(log_file, capsys):
    configure_logging(load_settings(env_file=None), console_level=logging.WARNING)

    logging.getLogger("src.app").info("routine detail")
    _flush()

    assert "routine detail" not in capsys.readouterr().out
    assert "routine detail" in log_file.read_text(encoding="utf-8")
