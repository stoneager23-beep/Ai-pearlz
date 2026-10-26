"""The composed retrieval-augmented answering chain (Task 07).

    {question, history}
      -> standalone_question   history-aware rewrite (memory.build_condenser)
      -> chunks                ScoredRetriever: top-k chunks with cosine scores
      -> gate                  relevance_gate: refuse without the model if nothing is relevant
      -> context               labelled [S1]..[Sk] blocks within the character budget
      -> draft                 prompt | chat model with structured output (AnswerDraft),
                               retried once if unreadable, then a safe fallback
      -> SupportResponse       citations validated and resolved, confidence decided

Every step is a LangChain runnable composed with LCEL, so callbacks (token counting, streaming,
tracing) reach both model calls. Timeouts and rate limits are retried with backoff inside the
OpenAI client; if they still fail, the exception leaves the chain and `SupportSession` turns it
into a readable response.
"""

from operator import itemgetter

from langchain_core.documents import Document
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import (
    Runnable,
    RunnableBranch,
    RunnableLambda,
    RunnablePassthrough,
)
from pydantic import ValidationError

from src.chains.citations import resolve_citations, strip_citation_markers
from src.chains.context import ContextBundle, build_context
from src.chains.memory import build_condenser
from src.chains.prompts import answer_prompt, format_question
from src.chains.schemas import (
    AnswerDraft,
    Confidence,
    GateInfo,
    RefusalReason,
    RetrievedChunk,
    SupportResponse,
)
from src.config import Settings
from src.retrieval.locations import location_label
from src.retrieval.retriever import SCORE_KEY, GateDecision, relevance_gate

ANSWER_TAG = "answer"
# One retry when the structured output cannot be read, then the fallback (manual Task 07).
STRUCTURED_OUTPUT_ATTEMPTS = 2
_CONFIDENCE_ORDER = (Confidence.NONE, Confidence.PARTIAL, Confidence.HIGH)


class UnreadableDraft(AnswerDraft):
    """Stands in for the model's answer when its output could not be parsed twice."""


def _unreadable_draft(support_contact: str) -> UnreadableDraft:
    return UnreadableDraft(
        answer=(
            "I couldn't put together a reliable answer this time. Please try again, or contact "
            f"Pearlz support: {support_contact}."
        ),
        sources=[],
        confidence=Confidence.NONE,
        answered=False,
    )


def gate_refusal_text(support_contact: str) -> str:
    return (
        "I can only answer questions about Pearlz products and policies from the Pearlz "
        "documentation, and I couldn't find anything there that answers this. I won't guess. "
        f"For help, please contact Pearlz support: {support_contact}."
    )


def decide_confidence(
    draft: AnswerDraft, gate: GateDecision, cited: int, invalid: int, high_score: float
) -> Confidence:
    """Combine the model's self-report with retrieval evidence (manual Feature 15).

    The model's own rating is the starting point and can only be lowered: to "none" if it did
    not answer; to "partial" if it answered without a single valid citation, cited a label that
    was never supplied, or the best chunk's similarity is below CONFIDENCE_HIGH_SCORE.
    """
    if not draft.answered or draft.confidence is Confidence.NONE:
        return Confidence.NONE
    ceiling = Confidence.HIGH
    weak_retrieval = gate.best_score is None or gate.best_score < high_score
    if cited == 0 or invalid > 0 or weak_retrieval:
        ceiling = Confidence.PARTIAL
    return min(draft.confidence, ceiling, key=_CONFIDENCE_ORDER.index)


def _retrieved(chunks: list[Document], context: ContextBundle | None) -> list[RetrievedChunk]:
    label_of = {
        id(chunk): label for label, chunk in (context.chunks_by_label.items() if context else [])
    }
    return [
        RetrievedChunk(
            label=label_of.get(id(chunk)),
            chunk_id=chunk.metadata["chunk_id"],
            source=chunk.metadata["source"],
            location=location_label(chunk.metadata),
            score=round(float(chunk.metadata[SCORE_KEY]), 4),
        )
        for chunk in chunks
    ]


def _finalise(
    state: dict, settings: Settings, model_name: str, prompt_version: str
) -> SupportResponse:
    gate: GateDecision = state["gate"]
    common = {
        "original_question": state["question"],
        "standalone_question": state["standalone_question"],
        "gate": GateInfo(
            passed=gate.passed,
            best_score=gate.best_score,
            threshold=gate.threshold,
            reason=gate.reason,
        ),
        "model": model_name,
        "prompt_version": prompt_version,
    }
    if not gate.passed:
        return SupportResponse(
            answer=gate_refusal_text(settings.support_contact),
            confidence=Confidence.NONE,
            answered=False,
            refusal_reason=RefusalReason.GATE,
            retrieved=_retrieved(state["chunks"], None),
            **common,
        )

    draft: AnswerDraft = state["draft"]
    context: ContextBundle = state["context"]
    resolved = resolve_citations(draft, context.chunks_by_label)
    unreadable = isinstance(draft, UnreadableDraft)
    confidence = decide_confidence(
        draft,
        gate,
        len(resolved.citations),
        len(resolved.invalid_labels),
        settings.confidence_high_score,
    )
    answered = draft.answered and confidence is not Confidence.NONE
    if unreadable:
        refusal = RefusalReason.ERROR
    elif not answered:
        refusal = RefusalReason.MODEL
    else:
        refusal = None
    return SupportResponse(
        answer=resolved.answer if answered else strip_citation_markers(resolved.answer),
        sources=resolved.citations if answered else [],
        confidence=confidence,
        answered=answered,
        refusal_reason=refusal,
        error_message="The model's answer could not be read." if unreadable else None,
        retrieved=_retrieved(state["chunks"], context),
        invalid_citations=resolved.invalid_labels,
        context_truncated=context.truncated,
        **common,
    )


def build_rag_chain(
    chat_model: BaseChatModel, retriever: BaseRetriever, settings: Settings
) -> Runnable:
    """The full chain from {"question": str, "history": list[Turn]} to a SupportResponse."""
    model_name = getattr(chat_model, "model_name", settings.openai_chat_model)
    prompt_version = f"{settings.answer_prompt_version}+{settings.condense_prompt_version}"
    structured_model = chat_model.with_structured_output(
        AnswerDraft, method="json_schema", strict=True
    ).with_config(tags=[ANSWER_TAG])
    drafter = (
        (answer_prompt(settings.answer_prompt_version, settings.support_contact) | structured_model)
        .with_retry(
            stop_after_attempt=STRUCTURED_OUTPUT_ATTEMPTS,
            retry_if_exception_type=(OutputParserException, ValidationError),
        )
        .with_fallbacks(
            [RunnableLambda(lambda _: _unreadable_draft(settings.support_contact))],
            exceptions_to_handle=(OutputParserException, ValidationError),
        )
    )
    draft_inputs = RunnableLambda(
        lambda state: {
            "context": state["context"].text,
            "question": format_question(state["question"], state["standalone_question"]),
        }
    )
    generate = RunnablePassthrough.assign(
        context=lambda state: build_context(state["chunks"], settings.max_context_characters)
    ) | RunnablePassthrough.assign(draft=draft_inputs | drafter)

    return (
        RunnablePassthrough.assign(
            standalone_question=build_condenser(chat_model, settings.condense_prompt_version)
        )
        | RunnablePassthrough.assign(chunks=itemgetter("standalone_question") | retriever)
        | RunnablePassthrough.assign(
            gate=lambda state: relevance_gate(state["chunks"], settings.relevance_threshold)
        )
        | RunnableBranch((lambda state: state["gate"].passed, generate), RunnablePassthrough())
        | RunnableLambda(lambda state: _finalise(state, settings, model_name, prompt_version))
    ).with_config(run_name="support_answer")
