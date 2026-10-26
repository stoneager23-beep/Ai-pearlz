"""Pydantic models for what the model must return and what the system returns (Tasks 07, 10).

`AnswerDraft` is the model's structured output: the four fields the manual requires. It is
validated before anything else touches it.

`SupportResponse` is what every interface (CLI, web app, evaluation) receives: the validated
answer, the resolved citations, and the diagnostics shown in the "Behind the answer" panel and
written to the log. It is returned in every case, including refusals and errors.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    HIGH = "high"
    PARTIAL = "partial"
    NONE = "none"


class RefusalReason(StrEnum):
    """Why an answer was not (fully) given."""

    GATE = "gate"  # retrieval found nothing relevant; the chat model was not called
    MODEL = "model"  # the model judged the context insufficient
    ERROR = "error"  # a technical failure, described in `error_message`


class AnswerDraft(BaseModel):
    """The chat model's structured output. Field order matters: `answer` streams first.

    The descriptions are deliberately neutral: every behavioural rule (grounding, refusal,
    citations) lives in the versioned prompts, so the weak and the grounded prompt can be
    compared with the same schema.
    """

    answer: str = Field(description="The reply to the customer.")
    sources: list[str] = Field(description="Labels of the context blocks used, such as S1.")
    confidence: Confidence = Field(
        description="high, partial or none: how completely the context answers the question."
    )
    answered: bool = Field(description="Whether the question was answered.")


class Citation(BaseModel):
    """One de-duplicated source shown under an answer."""

    number: int
    source: str
    doc_title: str
    location: str
    snippet: str
    labels: list[str]
    chunk_ids: list[str]


class RetrievedChunk(BaseModel):
    """A chunk the retriever returned, as shown in the "Behind the answer" panel."""

    label: str | None
    chunk_id: str
    source: str
    location: str
    score: float


class GateInfo(BaseModel):
    passed: bool
    best_score: float | None
    threshold: float
    reason: str


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class SupportResponse(BaseModel):
    """The answer to one turn, always schema-valid, whatever happened."""

    answer: str
    sources: list[Citation] = Field(default_factory=list)
    confidence: Confidence
    answered: bool
    refusal_reason: RefusalReason | None = None
    error_message: str | None = None

    original_question: str
    standalone_question: str
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    gate: GateInfo | None = None
    invalid_citations: list[str] = Field(default_factory=list)
    context_truncated: bool = False
    model: str
    prompt_version: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = 0
