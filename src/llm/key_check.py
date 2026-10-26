"""Check a pasted OpenAI API key before the web app uses it.

The check runs in order, stopping at the first problem:

1. Format, with no network call: catches empty, truncated, mis-pasted or admin keys.
2. One embedding request for the word "ping" (about 1 token). A free call such as listing
   models would succeed for a key whose account has no credit; a real, tiny billable request
   also catches "no credit", "no access to this model", rate limits, timeouts and outages.
3. List the models the key may use, so the model picker only offers models that will work.

Every failure becomes a distinct, human message (`src.errors.describe_failure`). The key is never
logged: failures are logged by exception type and status code only.
"""

import logging
from dataclasses import dataclass

import openai
from openai import OpenAI

from src.config import Settings
from src.errors import FailureKind, describe_failure, log_detail
from src.utils.api_keys import check_key_format

# A person is waiting on this check, so it fails fast instead of retrying.
VALIDATION_TIMEOUT_SECONDS = 15
VALIDATION_INPUT = "ping"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyCheck:
    ok: bool
    message: str
    available_models: tuple[str, ...] = ()
    kind: FailureKind | None = None


def validate_api_key(api_key: str, settings: Settings, client: OpenAI | None = None) -> KeyCheck:
    """Decide whether `api_key` can run this app, and which offered chat models it may use."""
    problem = check_key_format(api_key)
    if problem is not None:
        return KeyCheck(ok=False, message=problem.value, kind=FailureKind.CONFIGURATION)

    client = client or OpenAI(
        api_key=api_key.strip(), timeout=VALIDATION_TIMEOUT_SECONDS, max_retries=0
    )
    try:
        client.embeddings.create(model=settings.openai_embedding_model, input=VALIDATION_INPUT)
        listed = {model.id for model in client.models.list()}
    except openai.OpenAIError as error:
        logger.info("API key check failed: %s", log_detail(error))
        failure = describe_failure(error)
        return KeyCheck(ok=False, message=failure.message, kind=failure.kind)

    usable = tuple(name for name in settings.openai_chat_models if name in listed)
    if not usable:
        logger.info("API key check: none of the offered chat models is available to the key")
        return KeyCheck(
            ok=False,
            message=(
                "This key works, but it cannot use any of the chat models this app offers "
                f"({', '.join(settings.openai_chat_models)}). Check the key's project permissions."
            ),
            kind=FailureKind.NO_MODEL_ACCESS,
        )
    logger.info("API key accepted; %d of the offered chat models available", len(usable))
    return KeyCheck(ok=True, message="Key accepted.", available_models=usable)
