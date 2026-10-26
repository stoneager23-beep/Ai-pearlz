"""One conversation: memory, the chain, error handling and per-turn logging.

The CLI, the evaluation harness and the web app all talk to the system through
`SupportSession.ask`, so they behave identically. `ask` never raises: a timeout, a rate limit
or an unreadable answer comes back as a schema-valid `SupportResponse` with a readable message.

Each turn writes one structured log line (manual Feature 12): session id, original and
rewritten question, retrieved chunk ids with scores, gate decision, refusal, confidence,
citations, model, tokens, latency and, on failure, the error type. The API key never appears
in it; the log handlers redact anything key-shaped anyway.
"""

import json
import logging
import time
import uuid

from langchain_community.vectorstores import FAISS
from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel

from src.chains.memory import ConversationMemory
from src.chains.rag_chain import build_rag_chain
from src.chains.schemas import Confidence, RefusalReason, SupportResponse, TokenUsage
from src.config import Settings
from src.errors import describe_failure, log_detail
from src.llm.clients import build_chat_model, build_embeddings
from src.retrieval.retriever import build_retriever
from src.retrieval.shared_index import SharedIndex

MILLISECONDS = 1000
SESSION_ID_LENGTH = 8

logger = logging.getLogger(__name__)


def new_session_id() -> str:
    return uuid.uuid4().hex[:SESSION_ID_LENGTH]


class SupportSession:
    """A customer conversation with its own memory, model choice and filters."""

    def __init__(
        self,
        settings: Settings,
        store: FAISS,
        chat_model: BaseChatModel,
        *,
        session_id: str | None = None,
        doc_types: tuple[str, ...] = (),
        product_line: str | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.chat_model = chat_model
        self.session_id = session_id or new_session_id()
        self.memory = ConversationMemory(settings.history_turns)
        self.set_filters(doc_types=doc_types, product_line=product_line)

    @property
    def model_name(self) -> str:
        return getattr(self.chat_model, "model_name", self.settings.openai_chat_model)

    def set_filters(
        self, *, doc_types: tuple[str, ...] = (), product_line: str | None = None
    ) -> None:
        """Restrict retrieval by document type and product line (manual Feature 16)."""
        self.doc_types = doc_types
        self.product_line = product_line
        retriever = build_retriever(
            self.store, self.settings, doc_types=doc_types, product_line=product_line
        )
        self.chain = build_rag_chain(self.chat_model, retriever, self.settings)

    def set_chat_model(self, chat_model: BaseChatModel) -> None:
        """Answer with another model from the next turn on, keeping the conversation."""
        self.chat_model = chat_model
        self.set_filters(doc_types=self.doc_types, product_line=self.product_line)
        logger.info("Session %s now answers with %s", self.session_id, self.model_name)

    def reset(self) -> None:
        """Forget the conversation (the CLI's /reset and the app's "New conversation")."""
        self.memory.reset()
        logger.info("Session %s reset", self.session_id)

    def ask(
        self, question: str, callbacks: list[BaseCallbackHandler] | None = None
    ) -> SupportResponse:
        """Answer one turn. Never raises; failures come back as readable responses."""
        usage_handler = UsageMetadataCallbackHandler()
        started = time.perf_counter()
        error_detail = None
        try:
            response: SupportResponse = self.chain.invoke(
                {"question": question, "history": self.memory.turns},
                config={
                    "callbacks": [usage_handler, *(callbacks or [])],
                    "metadata": {"session_id": self.session_id},
                },
            )
        except Exception as error:  # the session boundary: every failure becomes a response
            error_detail = log_detail(error)
            logger.warning(
                "Session %s turn failed: %s", self.session_id, error_detail, exc_info=True
            )
            response = self._error_response(question, describe_failure(error).message)

        response = response.model_copy(
            update={
                "usage": _sum_usage(usage_handler),
                "latency_ms": round((time.perf_counter() - started) * MILLISECONDS),
            }
        )
        if response.refusal_reason is not RefusalReason.ERROR:
            self.memory.add(question, response.answer)
        self._log_turn(response, error_detail)
        return response

    def _error_response(self, question: str, message: str) -> SupportResponse:
        return SupportResponse(
            answer=message,
            confidence=Confidence.NONE,
            answered=False,
            refusal_reason=RefusalReason.ERROR,
            error_message=message,
            original_question=question,
            standalone_question=question,
            model=self.model_name,
            prompt_version=(
                f"{self.settings.answer_prompt_version}+{self.settings.condense_prompt_version}"
            ),
        )

    def _log_turn(self, response: SupportResponse, error_detail: str | None) -> None:
        record = {
            "event": "turn",
            "session": self.session_id,
            "question": response.original_question,
            "standalone_question": response.standalone_question,
            "retrieved": [[chunk.chunk_id, chunk.score] for chunk in response.retrieved],
            "gate_passed": response.gate.passed if response.gate else None,
            "best_score": response.gate.best_score if response.gate else None,
            "answered": response.answered,
            "refusal": response.refusal_reason,
            "confidence": response.confidence,
            "citations": [f"{c.source} {c.location}" for c in response.sources],
            "invalid_citations": response.invalid_citations,
            "context_truncated": response.context_truncated,
            "model": response.model,
            "prompt": response.prompt_version,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "latency_ms": response.latency_ms,
            "error": error_detail,
        }
        logger.info("turn %s", json.dumps(record, ensure_ascii=False))


def _sum_usage(handler: UsageMetadataCallbackHandler) -> TokenUsage:
    usage = handler.usage_metadata.values()
    return TokenUsage(
        input_tokens=sum(item.get("input_tokens", 0) for item in usage),
        output_tokens=sum(item.get("output_tokens", 0) for item in usage),
    )


def build_user_session(
    settings: Settings,
    shared_index: SharedIndex,
    api_key: str,
    model_name: str | None = None,
    *,
    streaming: bool = False,
    doc_types: tuple[str, ...] = (),
    product_line: str | None = None,
) -> SupportSession:
    """A session for one person: their key, their clients, their memory.

    Everything that holds the key (the embeddings that embed this person's questions and the
    chat model) is created here, for this session only. The only thing shared with other
    sessions is `shared_index`, which holds no key.
    """
    store = shared_index.store_for(build_embeddings(api_key, settings))
    chat_model = build_chat_model(api_key, settings, model_name, streaming=streaming)
    return SupportSession(
        settings, store, chat_model, doc_types=doc_types, product_line=product_line
    )
