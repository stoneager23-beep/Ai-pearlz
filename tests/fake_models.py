"""Deterministic stand-ins for OpenAI models, so tests never make network calls."""

import hashlib
from typing import Any

import numpy as np
from langchain_core.callbacks import CallbackManagerForLLMRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

OPENAI_SMALL_DIMENSION = 1536


class HashEmbeddings(Embeddings):
    """Unit-length vectors derived from a hash of the text: equal texts give equal vectors.

    Not semantic: use it to test plumbing (persistence, caching, ids), never retrieval quality.
    """

    def __init__(self, dimension: int = OPENAI_SMALL_DIMENSION) -> None:
        self.dimension = dimension
        self.texts_embedded = 0

    def _vector(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        vector = np.random.default_rng(seed).normal(size=self.dimension)
        return (vector / np.linalg.norm(vector)).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.texts_embedded += len(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class ScriptedChatModel(BaseChatModel):
    """A chat model that replays scripted replies.

    Plain calls (the condensation step) return the next string in `rewrites`. Structured-output
    calls (the answer step) return the next item in `drafts`, or raise it if it is an exception.
    Every prompt it receives is recorded, so tests can check what the model was shown.
    """

    model_name: str = "scripted-model"
    rewrites: list[str] = Field(default_factory=list)
    drafts: list[Any] = Field(default_factory=list)
    condense_prompts: list[list[BaseMessage]] = Field(default_factory=list)
    answer_prompts: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.condense_prompts.append(messages)
        reply = self.rewrites.pop(0)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable:
        def respond(prompt_value: Any) -> Any:
            self.answer_prompts.append(prompt_value)
            item = self.drafts.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return RunnableLambda(respond)


class FixedRetriever(BaseRetriever):
    """Returns the same scored documents for every query, and records the queries."""

    documents: list[Document]
    queries: list[str] = Field(default_factory=list)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        self.queries.append(query)
        return [
            Document(page_content=d.page_content, metadata=dict(d.metadata)) for d in self.documents
        ]
