"""Every failure becomes a distinct, human message that never contains key material."""

import httpx2
import openai
import pytest
from filelock import Timeout
from langchain_core.exceptions import OutputParserException

from src.errors import FailureKind, describe_failure, log_detail
from src.retrieval.vector_store import MissingIndexError

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


def _status_error(kind: type[openai.APIStatusError], status: int, code: str | None = None):
    body = {"code": code} if code else None
    message = "Incorrect API key provided: sk-proj-****************abcd"
    return kind(message, response=httpx2.Response(status, request=REQUEST), body=body)


CASES = [
    (_status_error(openai.AuthenticationError, 401, "invalid_api_key"), FailureKind.INVALID_KEY),
    (_status_error(openai.PermissionDeniedError, 403), FailureKind.NO_MODEL_ACCESS),
    (_status_error(openai.NotFoundError, 404, "model_not_found"), FailureKind.MODEL_NOT_FOUND),
    (_status_error(openai.RateLimitError, 429, "insufficient_quota"), FailureKind.NO_QUOTA),
    (_status_error(openai.RateLimitError, 429, "rate_limit_exceeded"), FailureKind.RATE_LIMITED),
    (openai.APITimeoutError(request=REQUEST), FailureKind.TIMEOUT),
    (openai.APIConnectionError(request=REQUEST), FailureKind.NETWORK),
    (_status_error(openai.InternalServerError, 503), FailureKind.SERVICE_DOWN),
    (
        _status_error(openai.BadRequestError, 400, "content_policy_violation"),
        FailureKind.CONTENT_FILTER,
    ),
    (openai.ContentFilterFinishReasonError(), FailureKind.CONTENT_FILTER),
    (_status_error(openai.BadRequestError, 400), FailureKind.BAD_REQUEST),
    (OutputParserException("Invalid json output"), FailureKind.MALFORMED_OUTPUT),
    (Timeout("pearlz_kb.lock"), FailureKind.BUILD_IN_PROGRESS),
    (MissingIndexError("No index has been built yet."), FailureKind.INDEX_PROBLEM),
    (RuntimeError("something internal"), FailureKind.UNEXPECTED),
]


@pytest.mark.parametrize(("error", "kind"), CASES)
def test_each_failure_maps_to_its_kind(error, kind):
    assert describe_failure(error).kind is kind


@pytest.mark.parametrize(("error", "kind"), CASES)
def test_messages_are_human_and_never_echo_the_exception(error, kind):
    message = describe_failure(error).message

    assert "sk-" not in message
    assert "Traceback" not in message
    assert message.endswith(".")


def test_quota_and_rate_limit_get_different_messages():
    quota = describe_failure(_status_error(openai.RateLimitError, 429, "insufficient_quota"))
    limited = describe_failure(_status_error(openai.RateLimitError, 429, "rate_limit_exceeded"))

    assert quota.message != limited.message
    assert not quota.retryable
    assert limited.retryable


def test_log_detail_records_type_status_and_code_only():
    error = _status_error(openai.AuthenticationError, 401, "invalid_api_key")

    assert log_detail(error) == "AuthenticationError status=401 code=invalid_api_key"
