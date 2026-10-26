"""Two people using the web app at once never share an object that holds an API key.

Only the key-free index data (SharedIndex) is shared between sessions; every client that holds
a key (chat model, query embeddings, the FAISS wrapper that uses them) is created per session.
"""

import pytest
from langchain_core.embeddings import Embeddings

from src.chains.session import build_user_session
from src.config import load_settings
from src.ingestion.embedding_cache import cached_embedder_from
from src.ingestion.indexing import sync_index
from src.retrieval.shared_index import load_shared_index
from tests.fake_models import HashEmbeddings
from tests.kb_builders import build_mixed_knowledge_base

KEY_A = "sk-proj-" + "AliceOnlyTestKey0123456789" * 3
KEY_B = "sk-proj-" + "BobOnlyTestKey0123456789x" * 3


@pytest.fixture
def shared(tmp_path, monkeypatch):
    build_mixed_knowledge_base(tmp_path / "kb")
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("EMBEDDING_CACHE_PATH", str(tmp_path / "cache.sqlite3"))
    settings = load_settings(env_file=None)
    sync_index(settings, cached_embedder_from(HashEmbeddings(), settings))
    return settings, load_shared_index(settings)


def _secret(model: object, field: str) -> str:
    return getattr(model, field).get_secret_value()


def test_sessions_with_different_keys_share_no_client(shared):
    settings, shared_index = shared

    alice = build_user_session(settings, shared_index, KEY_A, streaming=True)
    bob = build_user_session(settings, shared_index, KEY_B, streaming=True)

    assert alice.chat_model is not bob.chat_model
    assert alice.store is not bob.store
    assert alice.store.embeddings is not bob.store.embeddings
    assert alice.chain is not bob.chain
    assert _secret(alice.chat_model, "openai_api_key") == KEY_A
    assert _secret(bob.chat_model, "openai_api_key") == KEY_B
    assert _secret(alice.store.embeddings, "openai_api_key") == KEY_A
    assert _secret(bob.store.embeddings, "openai_api_key") == KEY_B


def test_only_key_free_index_data_is_shared(shared):
    settings, shared_index = shared

    alice = build_user_session(settings, shared_index, KEY_A)
    bob = build_user_session(settings, shared_index, KEY_B)

    assert alice.store.index is bob.store.index is shared_index.index
    assert alice.store.docstore is bob.store.docstore is shared_index.docstore
    assert KEY_A not in repr(shared_index)
    assert KEY_B not in repr(shared_index)


def test_each_session_has_its_own_memory(shared):
    settings, shared_index = shared
    alice = build_user_session(settings, shared_index, KEY_A)
    bob = build_user_session(settings, shared_index, KEY_B)

    alice.memory.add("Alice's question", "Alice's answer")

    assert bob.memory.turns == []
    assert alice.session_id != bob.session_id


def test_the_shared_index_holds_no_embeddings_object(shared):
    _, shared_index = shared

    assert not any(isinstance(value, Embeddings) for value in vars(shared_index).values())
