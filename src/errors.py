"""Turn any failure into a short, human message (manual Feature 11).

Both the CLI and the web app call `describe_failure` and show only its `message`. Raw exception
text is never shown: OpenAI's own messages can contain part of the API key ("Incorrect API key
provided: sk-proj-****abcd"), request ids and internal detail. The log records the exception
type and status code; the redaction filter covers anything else.
"""

from dataclasses import dataclass
from enum import StrEnum

import openai
from filelock import Timeout as LockTimeout
from langchain_core.exceptions import OutputParserException

from src.config import ConfigError
from src.ingestion.chunking import ChunkTooLongError
from src.ingestion.loaders import IngestionError
from src.retrieval.vector_store import VectorStoreError
from src.utils.api_keys import ApiKeyError

PLATFORM_KEYS_URL = "https://platform.openai.com/api-keys"
_QUOTA_CODES = frozenset({"insufficient_quota", "billing_hard_limit_reached"})
_CONTENT_FILTER_CODES = frozenset({"content_filter", "content_policy_violation"})


class FailureKind(StrEnum):
    INVALID_KEY = "invalid_key"
    NO_MODEL_ACCESS = "no_model_access"
    MODEL_NOT_FOUND = "model_not_found"
    NO_QUOTA = "no_quota"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVICE_DOWN = "service_down"
    CONTENT_FILTER = "content_filter"
    MALFORMED_OUTPUT = "malformed_output"
    BAD_REQUEST = "bad_request"
    INDEX_PROBLEM = "index_problem"
    BUILD_IN_PROGRESS = "build_in_progress"
    CONFIGURATION = "configuration"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class UserFacingError:
    kind: FailureKind
    message: str
    retryable: bool


def _openai_failure(error: openai.OpenAIError) -> UserFacingError:
    code = getattr(error, "code", None)
    if isinstance(error, openai.AuthenticationError):
        return UserFacingError(
            FailureKind.INVALID_KEY,
            "OpenAI did not accept this API key. Check that it was copied in full, or create a "
            f"new one at {PLATFORM_KEYS_URL}.",
            retryable=False,
        )
    if isinstance(error, openai.PermissionDeniedError):
        return UserFacingError(
            FailureKind.NO_MODEL_ACCESS,
            "This API key is not allowed to use the model. In your OpenAI project settings, check "
            "which models the key may use.",
            retryable=False,
        )
    if isinstance(error, openai.NotFoundError):
        return UserFacingError(
            FailureKind.MODEL_NOT_FOUND,
            "The selected model is not available to this API key. Try another model.",
            retryable=False,
        )
    if isinstance(error, openai.RateLimitError) and code in _QUOTA_CODES:
        return UserFacingError(
            FailureKind.NO_QUOTA,
            "This API key has no credit left. Add credit or a payment method in your OpenAI "
            "account's billing settings, then try again.",
            retryable=False,
        )
    if isinstance(error, openai.RateLimitError):
        return UserFacingError(
            FailureKind.RATE_LIMITED,
            "OpenAI is limiting requests from this key right now. Wait a minute and try again.",
            retryable=True,
        )
    if isinstance(error, openai.APITimeoutError):
        return UserFacingError(
            FailureKind.TIMEOUT,
            "OpenAI took too long to respond. Please try again.",
            retryable=True,
        )
    if isinstance(error, openai.APIConnectionError):
        return UserFacingError(
            FailureKind.NETWORK,
            "Could not reach OpenAI. Check your internet connection and try again.",
            retryable=True,
        )
    if isinstance(error, openai.InternalServerError):
        return UserFacingError(
            FailureKind.SERVICE_DOWN,
            "OpenAI is having problems at the moment. Please try again in a few minutes.",
            retryable=True,
        )
    if isinstance(error, openai.ContentFilterFinishReasonError) or code in _CONTENT_FILTER_CODES:
        return UserFacingError(
            FailureKind.CONTENT_FILTER,
            "OpenAI's safety filter blocked this request. Please rephrase your question.",
            retryable=False,
        )
    if isinstance(error, openai.LengthFinishReasonError):
        return UserFacingError(
            FailureKind.MALFORMED_OUTPUT,
            "The answer was cut off before it was complete. Please try again.",
            retryable=True,
        )
    return UserFacingError(
        FailureKind.BAD_REQUEST,
        "OpenAI could not process this request. Please try again or rephrase the question.",
        retryable=False,
    )


def describe_failure(error: BaseException) -> UserFacingError:
    """A short, safe description of `error` for the person using the system."""
    if isinstance(error, openai.OpenAIError):
        return _openai_failure(error)
    if isinstance(error, OutputParserException):
        return UserFacingError(
            FailureKind.MALFORMED_OUTPUT,
            "The answer could not be read in the expected format. Please try again.",
            retryable=True,
        )
    if isinstance(error, LockTimeout):
        return UserFacingError(
            FailureKind.BUILD_IN_PROGRESS,
            "The knowledge base is still being prepared by another session. Please try again "
            "in a minute.",
            retryable=True,
        )
    if isinstance(error, VectorStoreError | IngestionError | ChunkTooLongError):
        return UserFacingError(FailureKind.INDEX_PROBLEM, str(error), retryable=False)
    if isinstance(error, ConfigError | ApiKeyError):
        return UserFacingError(FailureKind.CONFIGURATION, str(error), retryable=False)
    return UserFacingError(
        FailureKind.UNEXPECTED,
        "Something went wrong on our side. The details are in the log.",
        retryable=True,
    )


def log_detail(error: BaseException) -> str:
    """What the log records about a failure: type and status code, never the raw message."""
    status = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    parts = [type(error).__name__]
    if status is not None:
        parts.append(f"status={status}")
    if code:
        parts.append(f"code={code}")
    return " ".join(parts)
