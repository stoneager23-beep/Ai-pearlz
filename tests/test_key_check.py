"""Key validation gives distinct messages per failure and never logs the key. No network."""

import logging
from types import SimpleNamespace

import httpx2
import openai
import pytest

from src.config import load_settings
from src.errors import FailureKind
from src.llm.key_check import validate_api_key

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")


def _status(kind: type[openai.APIStatusError], status: int, code: str | None = None):
    body = {"code": code} if code else None
    return kind("error", response=httpx2.Response(status, request=REQUEST), body=body)


class FakeOpenAI:
    """Stands in for the OpenAI client: one embeddings call, then a model listing."""

    def __init__(self, error: Exception | None = None, models: tuple[str, ...] = ()) -> None:
        self.calls = 0
        self.error = error
        self.embeddings = SimpleNamespace(create=self._create)
        self.models = SimpleNamespace(list=lambda: [SimpleNamespace(id=name) for name in models])

    def _create(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error


@pytest.fixture
def settings():
    return load_settings(env_file=None)


def test_malformed_key_is_rejected_without_any_network_call(settings):
    client = FakeOpenAI()

    result = validate_api_key("not-a-key", settings, client=client)

    assert not result.ok
    assert client.calls == 0
    assert 'start with "sk-"' in result.message


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (_status(openai.AuthenticationError, 401, "invalid_api_key"), FailureKind.INVALID_KEY),
        (_status(openai.RateLimitError, 429, "insufficient_quota"), FailureKind.NO_QUOTA),
        (_status(openai.RateLimitError, 429, "rate_limit_exceeded"), FailureKind.RATE_LIMITED),
        (_status(openai.PermissionDeniedError, 403), FailureKind.NO_MODEL_ACCESS),
        (openai.APITimeoutError(request=REQUEST), FailureKind.TIMEOUT),
        (openai.APIConnectionError(request=REQUEST), FailureKind.NETWORK),
        (_status(openai.InternalServerError, 503), FailureKind.SERVICE_DOWN),
    ],
)
def test_each_failure_has_its_own_message(settings, fake_key, error, kind):
    result = validate_api_key(fake_key, settings, client=FakeOpenAI(error=error))

    assert not result.ok
    assert result.kind is kind
    assert "sk-" not in result.message


def test_distinct_failures_give_distinct_messages(settings, fake_key):
    messages = {
        validate_api_key(fake_key, settings, client=FakeOpenAI(error=error)).message
        for error in (
            _status(openai.AuthenticationError, 401),
            _status(openai.RateLimitError, 429, "insufficient_quota"),
            _status(openai.RateLimitError, 429, "rate_limit_exceeded"),
            openai.APITimeoutError(request=REQUEST),
            _status(openai.InternalServerError, 500),
        )
    }

    assert len(messages) == 5


def test_valid_key_lists_only_the_offered_models_it_can_use(settings, fake_key):
    client = FakeOpenAI(models=("gpt-4o", "gpt-4.1-mini", "some-other-model"))

    result = validate_api_key(fake_key, settings, client=client)

    assert result.ok
    assert result.available_models == ("gpt-4.1-mini", "gpt-4o")


def test_key_that_can_use_no_offered_model_is_explained(settings, fake_key):
    result = validate_api_key(
        fake_key, settings, client=FakeOpenAI(models=("text-embedding-3-small",))
    )

    assert not result.ok
    assert result.kind is FailureKind.NO_MODEL_ACCESS


def test_the_key_never_reaches_the_log(settings, fake_key, caplog):
    with caplog.at_level(logging.DEBUG):
        validate_api_key(
            fake_key, settings, client=FakeOpenAI(error=_status(openai.AuthenticationError, 401))
        )
        validate_api_key(fake_key, settings, client=FakeOpenAI(models=("gpt-4.1-mini",)))

    assert caplog.records
    assert all(fake_key not in record.getMessage() for record in caplog.records)
