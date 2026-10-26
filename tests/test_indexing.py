"""Build once, load many times, update incrementally, refuse mismatches (Task 05).

All tests use a hash-based fake embedding model; nothing here calls OpenAI.
"""

import json

import pytest
from filelock import FileLock, Timeout

from src.config import load_settings
from src.errors import FailureKind, describe_failure
from src.ingestion.embedding_cache import cached_embedder_from
from src.ingestion.indexing import (
    SyncMode,
    file_fingerprints,
    index_is_current,
    load_or_build,
    sync_index,
)
from src.retrieval.vector_store import (
    IndexMismatchError,
    MissingIndexError,
    load_vector_store,
    manifest_path,
)
from tests.fake_models import HashEmbeddings
from tests.kb_builders import build_mixed_knowledge_base


@pytest.fixture
def settings(tmp_path, monkeypatch):
    build_mixed_knowledge_base(tmp_path / "kb")
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("EMBEDDING_CACHE_PATH", str(tmp_path / "cache" / "embeddings.sqlite3"))
    return load_settings(env_file=None)


def _embedder(settings):
    return cached_embedder_from(HashEmbeddings(), settings)


def test_first_sync_builds_and_second_is_up_to_date(settings):
    first = sync_index(settings, _embedder(settings))
    second_embedder = _embedder(settings)
    second = sync_index(settings, second_embedder)

    assert first.mode is SyncMode.FULL_BUILD
    assert first.texts_embedded == first.chunk_count > 0
    assert second.mode is SyncMode.UP_TO_DATE
    assert second_embedder.counter.texts_sent == 0


def test_index_survives_a_restart_without_re_embedding(settings):
    built = sync_index(settings, _embedder(settings))

    fresh = _embedder(settings)
    store, manifest = load_vector_store(fresh.embeddings, settings)

    assert store.index.ntotal == manifest.chunk_count == built.chunk_count
    assert fresh.counter.texts_sent == 0
    assert store.similarity_search_with_score("Return within 14 days.", k=1)


def test_changed_file_is_replaced_by_deleting_its_old_chunks(settings):
    sync_index(settings, _embedder(settings))
    policy = settings.knowledge_base_dir / "policy.md"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace("14 days", "30 days"), encoding="utf-8"
    )

    result = sync_index(settings, _embedder(settings))

    assert result.mode is SyncMode.INCREMENTAL
    assert result.changed == ["policy.md"]
    store, _ = load_vector_store(_embedder(settings).embeddings, settings)
    texts = [doc.page_content for doc in store.docstore._dict.values()]
    assert any("30 days" in text for text in texts)
    assert not any("14 days" in text for text in texts)


def test_only_the_changed_text_is_re_embedded(settings):
    sync_index(settings, _embedder(settings))
    policy = settings.knowledge_base_dir / "policy.md"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace("14 days", "30 days"), encoding="utf-8"
    )

    result = sync_index(settings, _embedder(settings))

    assert result.texts_embedded == 1


def test_removed_file_loses_its_chunks(settings):
    sync_index(settings, _embedder(settings))
    (settings.knowledge_base_dir / "notes.txt").unlink()

    result = sync_index(settings, _embedder(settings))

    assert result.removed == ["notes.txt"]
    _, manifest = load_vector_store(_embedder(settings).embeddings, settings)
    assert "notes.txt" not in manifest.chunk_ids_by_source


def test_changed_chunk_settings_force_a_full_rebuild(settings, monkeypatch):
    sync_index(settings, _embedder(settings))
    monkeypatch.setenv("CHUNK_SIZE", "300")
    monkeypatch.setenv("CHUNK_OVERLAP", "45")

    result = sync_index(load_settings(env_file=None), _embedder(settings))

    assert result.mode is SyncMode.FULL_BUILD
    assert "chunk size: index has 1500, settings say 300" in result.reason


def test_index_built_with_another_embedding_model_is_refused(settings, monkeypatch):
    sync_index(settings, _embedder(settings))
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

    with pytest.raises(IndexMismatchError, match="embedding model: index has text-embedding-3"):
        load_vector_store(HashEmbeddings(3072), load_settings(env_file=None))


def test_manifest_that_does_not_match_the_files_is_refused(settings):
    sync_index(settings, _embedder(settings))
    path = manifest_path(settings)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["chunk_count"] += 1
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(IndexMismatchError, match="do not match their manifest"):
        load_vector_store(_embedder(settings).embeddings, settings)


def test_missing_index_is_reported_and_load_or_build_builds_it(settings):
    with pytest.raises(MissingIndexError):
        load_vector_store(_embedder(settings).embeddings, settings)

    index = load_or_build(settings, _embedder(settings))

    assert index.sync is not None
    assert index.sync.mode is SyncMode.FULL_BUILD
    assert index_is_current(settings)


def test_load_or_build_does_no_work_when_the_index_is_current(settings):
    sync_index(settings, _embedder(settings))

    index = load_or_build(settings, _embedder(settings))

    assert index.sync is None


def test_fingerprints_ignore_line_endings_but_see_catalogue_changes(settings):
    kb_dir = settings.knowledge_base_dir
    policy = kb_dir / "policy.md"
    text = policy.read_bytes().replace(b"\r\n", b"\n")
    policy.write_bytes(text)
    before = file_fingerprints(kb_dir)
    policy.write_bytes(text.replace(b"\n", b"\r\n"))
    assert file_fingerprints(kb_dir) == before

    catalog = json.loads((kb_dir / "_catalog.json").read_text(encoding="utf-8"))
    catalog["policy.md"]["version"] = "2.0"
    (kb_dir / "_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    assert file_fingerprints(kb_dir)["policy.md"] != before["policy.md"]


def test_a_second_build_waits_for_the_first_and_then_reports_clearly(settings):
    settings.vector_store_dir.mkdir(parents=True)
    lock = FileLock(settings.vector_store_dir / f"{settings.collection_name}.lock")
    with lock, pytest.raises(Timeout) as raised:
        sync_index(settings, _embedder(settings), lock_timeout_seconds=0.1)

    assert describe_failure(raised.value).kind is FailureKind.BUILD_IN_PROGRESS
