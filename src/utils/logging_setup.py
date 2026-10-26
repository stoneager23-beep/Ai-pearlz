"""Central logging configuration: call `configure_logging` once per process.

Records go to standard output (Streamlit Cloud keeps stdout; its disk is wiped on restart)
and to a rotating file under LOG_DIR. Both handlers carry `ApiKeyRedactionFilter`.

The filter sits on the handlers, not on a logger. A logger-level filter only sees records
created on that exact logger, so a key inside an `openai` or `httpx` message would slip past.
Every record that reaches an output passes through a handler, so this placement covers them all.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from src.config import Settings
from src.utils.api_keys import redact_api_keys

LOG_FILE_NAME = "supportpearlz.log"

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
_MAX_LOG_FILE_BYTES = 5 * 1024 * 1024
_LOG_FILE_BACKUPS = 3
_HANDLER_NAME_PREFIX = "supportpearlz"
# Libraries that log one line per HTTP request at INFO. Their warnings still come through.
_CHATTY_LIBRARIES = ("httpx", "httpcore", "openai", "urllib3", "faiss")
# pypdf warns about every harmless quirk in a readable PDF. A file it cannot read is reported
# by the loader as one clear warning naming the file, so only pypdf's errors are kept.
_PDF_LIBRARY = "pypdf"


class ApiKeyRedactionFilter(logging.Filter):
    """Removes anything shaped like an OpenAI key from a record's message, traceback and stack."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            # A logging call with mismatched %-arguments; keep the raw parts rather than crash.
            message = f"{record.msg} {record.args}"
        record.msg = redact_api_keys(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_api_keys(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_api_keys(record.stack_info)
        return True


def configure_logging(settings: Settings) -> None:
    """Install the console and file handlers on the root logger.

    Safe to call repeatedly (Streamlit re-runs the script on every interaction): handlers
    installed by an earlier call are replaced, never duplicated.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() and handler.get_name().startswith(_HANDLER_NAME_PREFIX):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    redaction = ApiKeyRedactionFilter()

    console = logging.StreamHandler(sys.stdout)
    console.set_name(f"{_HANDLER_NAME_PREFIX}-console")

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = RotatingFileHandler(
        settings.log_dir / LOG_FILE_NAME,
        maxBytes=_MAX_LOG_FILE_BYTES,
        backupCount=_LOG_FILE_BACKUPS,
        encoding="utf-8",
    )
    log_file.set_name(f"{_HANDLER_NAME_PREFIX}-file")

    for handler in (console, log_file):
        handler.setFormatter(formatter)
        handler.addFilter(redaction)
        root.addHandler(handler)

    root.setLevel(settings.log_level)
    for library in _CHATTY_LIBRARIES:
        logging.getLogger(library).setLevel(logging.WARNING)
    logging.getLogger(_PDF_LIBRARY).setLevel(logging.ERROR)

    # If a handler itself fails (disk full, closed stream), the standard library prints the
    # original exception straight to stderr, bypassing every filter, so a key inside it would
    # leak. Turning this off makes such failures silent instead.
    logging.raiseExceptions = False
