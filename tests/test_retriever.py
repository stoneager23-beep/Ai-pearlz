"""The scored retriever and the relevance gate (Task 06). No OpenAI calls."""

import pytest
from langchain_core.documents import Document

from src.config import load_settings
from src.retrieval.retriever import (
    SCORE_KEY,
    ScoredRetriever,
    build_retriever,
    relevance_gate,
)
from src.retrieval.vector_store import create_vector_store
from tests.fake_models import HashEmbeddings


def _chunk(chunk_id: str, text: str, doc_type: str, product_lines: list[str]) -> Document:
    return Document(
        page_content=text,
        metadata={"chunk_id": chunk_id, "doc_type": doc_type, "product_lines": product_lines},
    )


CHUNKS = [
    _chunk("warranty::0", "Warranty is 24 months.", "policy", ["all"]),
    _chunk("manual::0", "Replace the PF-1 cartridge.", "manual", ["AquaPearl 500 Pro"]),
    _chunk("manual300::0", "Replace the CP-1 cartridge.", "manual", ["AquaPearl 300"]),
    _chunk("faq::0", "Delivery takes 1 to 2 days.", "faq", ["all"]),
]


@pytest.fixture
def store():
    return create_vector_store(CHUNKS, HashEmbeddings())


def test_retrieved_chunks_carry_their_cosine_score(store):
    results = ScoredRetriever(store=store, k=2).invoke("Warranty is 24 months.")

    assert results[0].metadata["chunk_id"] == "warranty::0"
    assert results[0].metadata[SCORE_KEY] == pytest.approx(1.0, abs=1e-5)
    assert len(results) == 2


def test_documents_inside_the_index_are_never_modified(store):
    ScoredRetriever(store=store, k=4).invoke("anything")

    for document in store.docstore._dict.values():
        assert SCORE_KEY not in document.metadata


def test_mmr_returns_k_distinct_chunks_with_scores(store):
    results = ScoredRetriever(store=store, search_type="mmr", k=3, fetch_k=4).invoke("cartridge")

    ids = [doc.metadata["chunk_id"] for doc in results]
    assert len(ids) == len(set(ids)) == 3
    assert all(SCORE_KEY in doc.metadata for doc in results)


def test_doc_type_filter(store):
    results = ScoredRetriever(store=store, k=4, doc_types=("manual",)).invoke("anything")

    assert {doc.metadata["doc_type"] for doc in results} == {"manual"}


def test_product_line_filter_keeps_documents_for_all_lines(store):
    results = ScoredRetriever(store=store, k=4, product_line="AquaPearl 300").invoke("anything")

    assert {doc.metadata["chunk_id"] for doc in results} == {
        "warranty::0",
        "manual300::0",
        "faq::0",
    }


def test_build_retriever_uses_the_settings(store, monkeypatch):
    monkeypatch.setenv("RETRIEVAL_SEARCH_TYPE", "mmr")
    monkeypatch.setenv("RETRIEVAL_K", "3")
    retriever = build_retriever(store, load_settings(env_file=None))

    assert (retriever.search_type, retriever.k) == ("mmr", 3)


def test_gate_refuses_when_nothing_was_retrieved():
    decision = relevance_gate([], threshold=0.3)

    assert not decision.passed
    assert decision.best_score is None


def test_gate_refuses_when_the_best_chunk_is_below_the_threshold():
    chunks = [Document(page_content="x", metadata={SCORE_KEY: 0.21})]

    decision = relevance_gate(chunks, threshold=0.3)

    assert not decision.passed
    assert "0.210 is below the threshold 0.30" in decision.reason


def test_gate_passes_on_the_best_chunk_not_the_first():
    chunks = [
        Document(page_content="x", metadata={SCORE_KEY: 0.1}),
        Document(page_content="y", metadata={SCORE_KEY: 0.45}),
    ]

    decision = relevance_gate(chunks, threshold=0.3)

    assert decision.passed
    assert decision.best_score == pytest.approx(0.45)
