"""The one place where OpenAI chat and embedding objects are created.

Every factory takes the API key as a required argument. Nothing here reads OPENAI_API_KEY from
the environment, and nothing here is cached: in the Streamlit app each visitor's session calls
these functions with that visitor's own key, so two sessions can never share a client that
holds someone else's key. Only key-free data (the index, the settings) is shared.
"""

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

from src.config import Settings


def build_embeddings(api_key: str, settings: Settings) -> OpenAIEmbeddings:
    """The embedding model used for both indexing and querying (they must never differ)."""
    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=SecretStr(api_key),
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        chunk_size=settings.embedding_batch_size,
    )


def build_chat_model(
    api_key: str,
    settings: Settings,
    model_name: str | None = None,
    *,
    streaming: bool = False,
) -> ChatOpenAI:
    """A chat model with the configured, explicit temperature.

    `model_name` lets a session pick one of the offered models; it defaults to
    OPENAI_CHAT_MODEL. `stream_usage` makes streamed responses report token counts too.
    """
    name = model_name or settings.openai_chat_model
    if name not in settings.openai_chat_models:
        raise ValueError(f"{name} is not one of the offered chat models")
    return ChatOpenAI(
        model=name,
        api_key=SecretStr(api_key),
        temperature=settings.llm_temperature,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        streaming=streaming,
        stream_usage=True,
    )
