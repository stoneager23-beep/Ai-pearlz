"""Build the index once, keep it up to date incrementally, and load it at query time (Task 05).

`sync_index` compares a fingerprint of every knowledge-base file with the fingerprints saved
in the index manifest and does the least work needed:

- **full build**: no index yet, `--rebuild` was asked for, or the index was built with other
  settings (embedding model, chunk size, overlap, headers). Everything is re-chunked; the
  embedding cache still makes unchanged chunks free.
- **incremental update**: some files were added, changed or removed. The chunks of changed and
  removed files are deleted by id, and only added and changed files are loaded, chunked and
  inserted. Deleting first matters: re-adding without deleting would leave the old and new
  versions of a policy both retrievable (viva Q20).
- **up to date**: nothing changed; nothing is loaded or embedded.

A file lock makes concurrent builds wait for each other (two Streamlit visitors arriving on a
fresh deployment, or a CLI build while the app runs) instead of both building.

`load_or_build` is what the query path calls: load the saved index if it matches the settings
and the files on disk, otherwise sync first, then load.
"""

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from filelock import FileLock
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from src.config import Settings
from src.ingestion.chunking import build_chunks
from src.ingestion.embedding_cache import CachedEmbedder, count_tokens
from src.ingestion.loaders import FileReport, FileStatus, load_knowledge_base, read_catalog
from src.retrieval.vector_store import (
    IndexManifest,
    IndexMismatchError,
    MissingIndexError,
    assert_unit_length,
    create_vector_store,
    load_vector_store,
    new_manifest,
    read_manifest,
    save_vector_store,
)

# Line endings are normalised before hashing text files, so a file checked out on Windows
# (CRLF) and on Linux (LF) has the same fingerprint and does not trigger a rebuild.
TEXT_SUFFIXES = frozenset({".md", ".txt", ".csv"})
BUILD_LOCK_TIMEOUT_SECONDS = 600

logger = logging.getLogger(__name__)


class SyncMode(StrEnum):
    FULL_BUILD = "full build"
    INCREMENTAL = "incremental update"
    UP_TO_DATE = "up to date"


@dataclass
class IndexSyncResult:
    mode: SyncMode
    reason: str
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    chunks_removed: int = 0
    chunks_added: int = 0
    chunk_count: int = 0
    texts_embedded: int = 0
    tokens_embedded: int = 0
    seconds: float = 0.0
    skipped_files: list[FileReport] = field(default_factory=list)


@dataclass(frozen=True)
class BuildEstimate:
    """What a full build would send to the embedding model."""

    documents: int
    chunks: int
    tokens: int


@dataclass
class LoadedIndex:
    store: FAISS
    manifest: IndexManifest
    sync: IndexSyncResult | None


def file_fingerprints(kb_dir: Path) -> dict[str, str]:
    """SHA-256 per catalogued file, over its content and its catalogue entry.

    Including the catalogue entry means a metadata change (a new version number, a different
    doc_type) also counts as a change to that file.
    """
    fingerprints = {}
    for name, entry in read_catalog(kb_dir).items():
        path = kb_dir / name
        if not path.is_file():
            continue
        content = path.read_bytes()
        if path.suffix.lower() in TEXT_SUFFIXES:
            content = content.replace(b"\r\n", b"\n")
        digest = hashlib.sha256(content)
        digest.update(entry.model_dump_json().encode("utf-8"))
        fingerprints[name] = digest.hexdigest()
    return fingerprints


def _ids_by_source(chunks: list[Document]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        grouped[chunk.metadata["source"]].append(chunk.metadata["chunk_id"])
    return dict(grouped)


def _skipped(reports: list[FileReport]) -> list[FileReport]:
    return [report for report in reports if report.status is FileStatus.SKIPPED]


def _full_build(
    settings: Settings, embedder: CachedEmbedder, fingerprints: dict[str, str], reason: str
) -> IndexSyncResult:
    logger.info("Full index build (%s)", reason)
    ingestion = load_knowledge_base(settings.knowledge_base_dir)
    chunks = build_chunks(ingestion.documents, settings)
    store = create_vector_store(chunks, embedder.embeddings)
    assert_unit_length(store)
    manifest = new_manifest(settings, fingerprints, _ids_by_source(chunks))
    save_vector_store(store, manifest, settings)
    return IndexSyncResult(
        mode=SyncMode.FULL_BUILD,
        reason=reason,
        added=sorted(fingerprints),
        chunks_added=len(chunks),
        chunk_count=manifest.chunk_count,
        skipped_files=_skipped(ingestion.reports),
    )


def _incremental_update(
    settings: Settings,
    embedder: CachedEmbedder,
    manifest: IndexManifest,
    fingerprints: dict[str, str],
) -> IndexSyncResult:
    old = manifest.file_fingerprints
    added = sorted(name for name in fingerprints if name not in old)
    removed = sorted(name for name in old if name not in fingerprints)
    changed = sorted(
        name for name in fingerprints if name in old and old[name] != fingerprints[name]
    )
    logger.info("Incremental update: added %s, changed %s, removed %s", added, changed, removed)

    store, _ = load_vector_store(embedder.embeddings, settings)
    ids_by_source = dict(manifest.chunk_ids_by_source)
    stale_ids = [chunk_id for name in changed + removed for chunk_id in ids_by_source.pop(name, [])]
    if stale_ids:
        store.delete(stale_ids)

    ingestion = load_knowledge_base(settings.knowledge_base_dir, only=set(added + changed))
    chunks = build_chunks(ingestion.documents, settings)
    if chunks:
        store.add_documents(chunks, ids=[chunk.metadata["chunk_id"] for chunk in chunks])
    assert_unit_length(store)
    ids_by_source |= _ids_by_source(chunks)

    updated = new_manifest(settings, fingerprints, ids_by_source)
    save_vector_store(store, updated, settings)
    return IndexSyncResult(
        mode=SyncMode.INCREMENTAL,
        reason=f"{len(added)} added, {len(changed)} changed, {len(removed)} removed",
        added=added,
        changed=changed,
        removed=removed,
        chunks_removed=len(stale_ids),
        chunks_added=len(chunks),
        chunk_count=updated.chunk_count,
        skipped_files=_skipped(ingestion.reports),
    )


def sync_index(
    settings: Settings,
    embedder: CachedEmbedder,
    *,
    rebuild: bool = False,
    lock_timeout_seconds: float = BUILD_LOCK_TIMEOUT_SECONDS,
) -> IndexSyncResult:
    """Bring the saved index in line with the knowledge base, doing as little work as possible.

    Raises filelock.Timeout if another process is still building after `lock_timeout_seconds`.
    """
    settings.vector_store_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(settings.vector_store_dir / f"{settings.collection_name}.lock")
    started = time.perf_counter()
    texts_before = embedder.counter.texts_sent
    tokens_before = embedder.counter.tokens_sent

    with lock.acquire(timeout=lock_timeout_seconds):
        fingerprints = file_fingerprints(settings.knowledge_base_dir)
        manifest = None
        try:
            manifest = read_manifest(settings)
            problems = manifest.problems_with(settings)
            reason = "settings changed: " + "; ".join(problems) if problems else ""
        except MissingIndexError:
            reason = "no saved index yet"
        except IndexMismatchError as error:
            reason = str(error)

        if rebuild or manifest is None or reason:
            result = _full_build(settings, embedder, fingerprints, reason or "--rebuild requested")
        elif manifest.file_fingerprints == fingerprints:
            result = IndexSyncResult(
                mode=SyncMode.UP_TO_DATE,
                reason="no file has changed since the last build",
                chunk_count=manifest.chunk_count,
            )
        else:
            result = _incremental_update(settings, embedder, manifest, fingerprints)

    result.texts_embedded = embedder.counter.texts_sent - texts_before
    result.tokens_embedded = embedder.counter.tokens_sent - tokens_before
    result.seconds = time.perf_counter() - started
    logger.info(
        "Index %s: %d chunks, %d texts (%d tokens) embedded, %.1fs",
        result.mode,
        result.chunk_count,
        result.texts_embedded,
        result.tokens_embedded,
        result.seconds,
    )
    return result


def index_is_current(settings: Settings) -> bool:
    """True if a saved index matches the settings and every file on disk (no loading needed)."""
    try:
        manifest = read_manifest(settings)
    except (MissingIndexError, IndexMismatchError):
        return False
    return not manifest.problems_with(settings) and manifest.file_fingerprints == (
        file_fingerprints(settings.knowledge_base_dir)
    )


def load_or_build(settings: Settings, embedder: CachedEmbedder) -> LoadedIndex:
    """The query path's entry point: load the saved index, building or updating it first if needed.

    `embedder` embeds queries against the loaded index and, only when a build is needed, the
    chunks. Its cache makes a rebuild cost nothing for chunks that were embedded before.
    """
    sync = None if index_is_current(settings) else sync_index(settings, embedder)
    store, manifest = load_vector_store(embedder.embeddings, settings)
    return LoadedIndex(store=store, manifest=manifest, sync=sync)


def estimate_build(settings: Settings) -> BuildEstimate:
    """Read and chunk the knowledge base locally to count what a full build would embed.

    No API call. It is an upper bound: chunks already in the embedding cache cost nothing.
    """
    ingestion = load_knowledge_base(settings.knowledge_base_dir)
    chunks = build_chunks(ingestion.documents, settings)
    tokens = sum(
        count_tokens(chunk.page_content, settings.openai_embedding_model) for chunk in chunks
    )
    return BuildEstimate(documents=ingestion.loaded_count, chunks=len(chunks), tokens=tokens)
