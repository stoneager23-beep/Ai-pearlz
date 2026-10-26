"""The composed chain: gate, generation, retries, confidence and citations (Tasks 07, 10)."""

import pytest
from langchain_core.exceptions import OutputParserException

from src.chains.memory import Turn
from src.chains.rag_chain import build_rag_chain
from src.chains.schemas import Confidence, RefusalReason, SupportResponse
from src.config import load_settings
from tests.chain_fixtures import draft, scored_chunk
from tests.fake_models import FixedRetriever, ScriptedChatModel

HIGH = 0.72
BELOW_GATE = 0.20
BELOW_HIGH = 0.42


@pytest.fixture
def settings():
    return load_settings(env_file=None)


def _run(
    settings, chunks, drafts, *, history=None, rewrites=None
) -> tuple[SupportResponse, ScriptedChatModel]:
    model = ScriptedChatModel(drafts=list(drafts), rewrites=list(rewrites or []))
    chain = build_rag_chain(model, FixedRetriever(documents=chunks), settings)
    response = chain.invoke({"question": "How long is the warranty?", "history": history or []})
    return response, model


def test_gate_refuses_without_calling_the_model(settings):
    response, model = _run(
        settings, [scored_chunk("w::0", "Unrelated text.", BELOW_GATE)], drafts=[]
    )

    assert response.refusal_reason is RefusalReason.GATE
    assert not response.answered
    assert response.confidence is Confidence.NONE
    assert response.sources == []
    assert model.answer_prompts == []
    assert "Pearlz support" in response.answer


def test_answer_with_resolved_citation(settings):
    chunks = [scored_chunk("w::0", "AquaPearl 500 Pro: 24 months.", HIGH)]

    response, _ = _run(settings, chunks, [draft("The warranty is 24 months [S1].", ["S1"])])

    assert response.answered
    assert response.confidence is Confidence.HIGH
    assert response.answer == "The warranty is 24 months [1]."
    assert [(c.number, c.source, c.location) for c in response.sources] == [
        (1, "warranty_policy.md", "§2. Warranty periods")
    ]
    assert response.sources[0].snippet == "AquaPearl 500 Pro: 24 months."


def test_retrieved_but_uncited_chunks_are_not_listed_as_sources(settings):
    chunks = [
        scored_chunk("w::0", "24 months.", HIGH),
        scored_chunk(
            "r::0", "14 days.", 0.6, source="refund_returns_policy.md", section="1. Window"
        ),
    ]

    response, _ = _run(settings, chunks, [draft("24 months [S1].", ["S1"])])

    assert [citation.source for citation in response.sources] == ["warranty_policy.md"]
    assert len(response.retrieved) == 2


def test_fabricated_label_is_dropped_and_lowers_confidence(settings):
    chunks = [scored_chunk("w::0", "24 months.", HIGH)]

    response, _ = _run(settings, chunks, [draft("24 months [S1][S5].", ["S1", "S5"])])

    assert response.invalid_citations == ["S5"]
    assert response.answer == "24 months [1]."
    assert len(response.sources) == 1
    assert response.confidence is Confidence.PARTIAL


def test_answer_without_any_valid_citation_is_only_partial(settings):
    chunks = [scored_chunk("w::0", "24 months.", HIGH)]

    response, _ = _run(settings, chunks, [draft("It is 24 months.", [])])

    assert response.confidence is Confidence.PARTIAL


def test_weak_retrieval_caps_confidence_at_partial(settings):
    chunks = [scored_chunk("w::0", "24 months.", BELOW_HIGH)]

    response, _ = _run(settings, chunks, [draft("24 months [S1].", ["S1"])])

    assert response.confidence is Confidence.PARTIAL


def test_model_refusal_is_reported_as_such(settings):
    chunks = [scored_chunk("w::0", "24 months.", HIGH)]
    refusal = draft("The documentation does not cover this.", [], Confidence.NONE, answered=False)

    response, _ = _run(settings, chunks, [refusal])

    assert response.refusal_reason is RefusalReason.MODEL
    assert response.sources == []


def test_unreadable_output_is_retried_once(settings):
    chunks = [scored_chunk("w::0", "24 months.", HIGH)]

    response, model = _run(
        settings, chunks, [OutputParserException("bad json"), draft("24 months [S1].", ["S1"])]
    )

    assert response.answered
    assert len(model.answer_prompts) == 2


def test_unreadable_output_twice_falls_back_safely(settings):
    chunks = [scored_chunk("w::0", "24 months.", HIGH)]

    response, _ = _run(
        settings, chunks, [OutputParserException("bad"), OutputParserException("still bad")]
    )

    assert isinstance(response, SupportResponse)
    assert response.refusal_reason is RefusalReason.ERROR
    assert not response.answered
    assert "try again" in response.answer


def test_context_blocks_are_labelled_and_shown_to_the_model(settings):
    chunks = [
        scored_chunk("w::0", "24 months.", HIGH),
        scored_chunk("w::1", "Invoice date.", 0.6, section="4.1 Start date"),
    ]

    _, model = _run(settings, chunks, [draft("24 months [S1].", ["S1"])])

    prompt_text = model.answer_prompts[0].to_string()
    assert (
        "[S1] Warranty Policy (warranty_policy.md), §2. Warranty periods; version 3.1"
        in prompt_text
    )
    assert "[S2] Warranty Policy (warranty_policy.md), §4.1 Start date" in prompt_text
    assert "<context>" in prompt_text


def test_follow_up_is_rewritten_before_retrieval(settings):
    chunks = [scored_chunk("w::0", "24 months.", HIGH)]
    history = [Turn("Tell me about the AquaPearl 500 Pro warranty.", "It is 24 months [1].")]
    model = ScriptedChatModel(
        rewrites=["Is the PF-1 filter covered by the AquaPearl 500 Pro warranty?"],
        drafts=[draft("No [S1].", ["S1"])],
    )
    retriever = FixedRetriever(documents=chunks)

    response = build_rag_chain(model, retriever, settings).invoke(
        {"question": "is that covered?", "history": history}
    )

    assert retriever.queries == ["Is the PF-1 filter covered by the AquaPearl 500 Pro warranty?"]
    assert response.standalone_question == retriever.queries[0]
    assert response.original_question == "is that covered?"


def test_first_turn_is_not_rewritten(settings):
    chunks = [scored_chunk("w::0", "24 months.", HIGH)]

    response, model = _run(settings, chunks, [draft("24 months [S1].", ["S1"])])

    assert model.condense_prompts == []
    assert response.standalone_question == response.original_question
