"""Cached, batched, token-counted embeddings for building indexes (Task 04).

Embedding calls cost the user money, so a chunk is never embedded twice:

- `CacheBackedEmbeddings` (LangChain) looks every text up in a byte store first and sends only
  the misses to OpenAI, in batches of EMBEDDING_BATCH_SIZE. Each finished batch is written to
  the store before the next one starts, so a crash at 80% loses at most one batch.
- `SQLiteByteStore` is that byte store: one SQLite file instead of thousands of small files.
  Keys combine the model name and a SHA-256 of the text, so vectors from one model are never
  reused for another.
- `TokenCountingEmbeddings` counts the texts and tokens actually sent to OpenAI (cache misses
  only) and logs each batch with its duration.

Retries with exponential backoff on timeouts, rate limits and server errors are done by the
OpenAI client inside `OpenAIEmbeddings` (OPENAI_MAX_RETRIES).

The cache holds only vectors and hashes, never an API key, so it is safe to share between
Streamlit sessions.
"""

import logging
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import tiktoken
from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_core.stores import ByteStore

from src.config import Settings
from src.llm.clients import build_embeddings

# SQLite limits how many "?" placeholders one statement may have; stay well below it.
_SQL_BATCH = 500
_SQLITE_LOCK_TIMEOUT_SECONDS = 30

logger = logging.getLogger(__name__)


class SQLiteByteStore(ByteStore):
    """A LangChain byte store kept in one SQLite file. Opens a connection per call (thread-safe)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, value BLOB NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=_SQLITE_LOCK_TIMEOUT_SECONDS)

    def mget(self, keys: Sequence[str]) -> list[bytes | None]:
        found: dict[str, bytes] = {}
        with closing(self._connect()) as connection:
            for start in range(0, len(keys), _SQL_BATCH):
                batch = list(keys[start : start + _SQL_BATCH])
                placeholders = ",".join("?" * len(batch))
                rows = connection.execute(
                    f"SELECT key, value FROM entries WHERE key IN ({placeholders})", batch
                )
                found.update(rows)
        return [found.get(key) for key in keys]

    def mset(self, key_value_pairs: Sequence[tuple[str, bytes]]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                "INSERT OR REPLACE INTO entries (key, value) VALUES (?, ?)", key_value_pairs
            )

    def mdelete(self, keys: Sequence[str]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executemany("DELETE FROM entries WHERE key = ?", [(key,) for key in keys])

    def yield_keys(self, *, prefix: str | None = None) -> Iterator[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT key FROM entries WHERE key LIKE ? ORDER BY key", (f"{prefix or ''}%",)
            )
            for (key,) in rows:
                yield key


class TokenCountingEmbeddings(Embeddings):
    """Passes calls through to `inner`, counting the texts and tokens sent to the API."""

    def __init__(self, inner: Embeddings, model_name: str) -> None:
        self.inner = inner
        self.encoding = tiktoken.encoding_for_model(model_name)
        self.texts_sent = 0
        self.tokens_sent = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        tokens = sum(len(self.encoding.encode(text)) for text in texts)
        started = time.perf_counter()
        vectors = self.inner.embed_documents(texts)
        elapsed = time.perf_counter() - started
        self.texts_sent += len(texts)
        self.tokens_sent += tokens
        logger.info("Embedded %d chunks (%d tokens) in %.1fs", len(texts), tokens, elapsed)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(text)


@dataclass
class CachedEmbedder:
    """The cached embeddings object to index with, and the counter of what it actually sent."""

    embeddings: CacheBackedEmbeddings
    counter: TokenCountingEmbeddings


def build_cached_embedder(api_key: str, settings: Settings) -> CachedEmbedder:
    """Embeddings for index builds: cache first, then OpenAI in counted, retried batches."""
    return cached_embedder_from(build_embeddings(api_key, settings), settings)


def cached_embedder_from(underlying: Embeddings, settings: Settings) -> CachedEmbedder:
    """Wrap any embeddings model with the counter and the cache (tests pass a fake model)."""
    counter = TokenCountingEmbeddings(underlying, settings.openai_embedding_model)
    cached = CacheBackedEmbeddings.from_bytes_store(
        counter,
        SQLiteByteStore(settings.embedding_cache_path),
        namespace=settings.openai_embedding_model,
        batch_size=settings.embedding_batch_size,
        key_encoder="sha256",
    )
    return CachedEmbedder(embeddings=cached, counter=counter)


def count_tokens(text: str, model_name: str) -> int:
    """Tokens `text` costs with the tokenizer of `model_name`."""
    return len(tiktoken.encoding_for_model(model_name).encode(text))
