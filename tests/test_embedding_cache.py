"""The embedding cache: one SQLite file, resumable after a crash, and counted (Task 04).

Uses a fake embeddings model; these tests never call OpenAI.
"""

import pytest
from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain_core.embeddings import Embeddings

from src.ingestion.embedding_cache import SQLiteByteStore, TokenCountingEmbeddings


class FakeEmbeddings(Embeddings):
    """Returns a vector derived from the text; can be told to fail on a given call."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on_call = fail_on_call

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise ConnectionError("network dropped")
        return [[float(len(text)), 1.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


def _cached(inner: Embeddings, store: SQLiteByteStore, batch_size: int) -> CacheBackedEmbeddings:
    return CacheBackedEmbeddings.from_bytes_store(
        inner, store, namespace="test-model", batch_size=batch_size, key_encoder="sha256"
    )


def test_store_round_trip(tmp_path):
    store = SQLiteByteStore(tmp_path / "cache.sqlite3")
    store.mset([("a", b"1"), ("b", b"2")])

    assert store.mget(["a", "missing", "b"]) == [b"1", None, b"2"]
    store.mdelete(["a"])
    assert list(store.yield_keys()) == ["b"]


def test_cached_texts_are_never_embedded_twice(tmp_path):
    store = SQLiteByteStore(tmp_path / "cache.sqlite3")
    first = FakeEmbeddings()
    _cached(first, store, batch_size=2).embed_documents(["one", "two", "three"])

    second = FakeEmbeddings()
    vectors = _cached(second, store, batch_size=2).embed_documents(["one", "two", "three", "four"])

    assert second.calls == [["four"]]
    assert vectors[0] == [3.0, 1.0]


def test_a_crash_mid_run_keeps_the_finished_batches(tmp_path):
    store = SQLiteByteStore(tmp_path / "cache.sqlite3")
    texts = [f"chunk {n}" for n in range(10)]
    crashing = FakeEmbeddings(fail_on_call=3)
    with pytest.raises(ConnectionError):
        _cached(crashing, store, batch_size=4).embed_documents(texts)

    resumed = FakeEmbeddings()
    _cached(resumed, store, batch_size=4).embed_documents(texts)

    assert sum(len(call) for call in resumed.calls) == 2


def test_another_model_never_reuses_cached_vectors(tmp_path):
    store = SQLiteByteStore(tmp_path / "cache.sqlite3")
    _cached(FakeEmbeddings(), store, batch_size=8).embed_documents(["same text"])

    other = FakeEmbeddings()
    CacheBackedEmbeddings.from_bytes_store(
        other, store, namespace="other-model", key_encoder="sha256"
    ).embed_documents(["same text"])

    assert other.calls == [["same text"]]


def test_counter_records_texts_and_tokens_actually_sent():
    counter = TokenCountingEmbeddings(FakeEmbeddings(), "text-embedding-3-small")

    counter.embed_documents(["hello world", "pearl"])

    assert counter.texts_sent == 2
    # "hello world" is 2 tokens and "pearl" is 2 (OpenAI billed 2 tokens for "pearl" in a probe).
    assert counter.tokens_sent == 4
