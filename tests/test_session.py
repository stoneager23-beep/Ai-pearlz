"""SupportSession: never raises, remembers turns, logs every turn without the key."""

import json
import logging

import httpx2
import openai
import pytest
from langchain_core.documents import Document

from src.chains.schemas import RefusalReason
from src.chains.session import SupportSession
from src.config import load_settings
from src.retrieval.vector_store import create_vector_store
from tests.chain_fixtures import draft
from tests.fake_models import HashEmbeddings, ScriptedChatModel

QUESTION = "AquaPearl 500 Pro warranty: 24 months."


@pytest.fixture
def store():
    chunk = Document(
        page_content=QUESTION,
        metadata={
            "chunk_id": "w::0",
            "source": "warranty_policy.md",
            "doc_title": "Warranty Policy",
            "doc_type": "policy",
            "product_lines": ["all"],
            "version": "3.1",
            "last_updated": "2026-04-01",
            "section": "2. Warranty periods",
        },
    )
    return create_vector_store([chunk], HashEmbeddings())


def _session(store, model):
    return SupportSession(load_settings(env_file=None), store, model, session_id="test0001")


def test_successful_turn_is_remembered(store):
    session = _session(store, ScriptedChatModel(drafts=[draft("24 months [S1].", ["S1"])]))

    response = session.ask(QUESTION)

    assert response.answered
    assert [turn.question for turn in session.memory.turns] == [QUESTION]


def test_api_failure_becomes_a_readable_response_and_is_not_remembered(store):
    response_429 = httpx2.Response(
        429, request=httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    )
    quota = openai.RateLimitError(
        "quota", response=response_429, body={"code": "insufficient_quota"}
    )
    session = _session(store, ScriptedChatModel(drafts=[quota]))

    response = session.ask(QUESTION)

    assert response.refusal_reason is RefusalReason.ERROR
    assert "no credit left" in response.answer
    assert session.memory.turns == []


def test_each_turn_is_logged_as_one_structured_line(store, caplog, fake_key):
    session = _session(store, ScriptedChatModel(drafts=[draft("24 months [S1].", ["S1"])]))

    with caplog.at_level(logging.INFO, logger="src.chains.session"):
        session.ask(QUESTION)

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("turn ")]
    record = json.loads(lines[0].removeprefix("turn "))
    assert record["session"] == "test0001"
    assert record["question"] == QUESTION
    assert record["retrieved"][0][0] == "w::0"
    assert record["gate_passed"] is True
    assert {"standalone_question", "latency_ms", "input_tokens", "refusal"} <= set(record)
    assert fake_key not in lines[0]


def test_filters_rebuild_the_chain(store):
    session = _session(store, ScriptedChatModel())
    before = session.chain

    session.set_filters(doc_types=("policy",), product_line="AquaPearl 300")

    assert session.chain is not before
    assert (session.doc_types, session.product_line) == (("policy",), "AquaPearl 300")


def test_reset_forgets_the_conversation(store):
    session = _session(store, ScriptedChatModel(drafts=[draft("24 months [S1].", ["S1"])]))
    session.ask(QUESTION)

    session.reset()

    assert session.memory.turns == []
