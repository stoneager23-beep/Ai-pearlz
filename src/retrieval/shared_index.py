"""Index data that every web session can share, because it contains no API key.

LangChain's FAISS object keeps a reference to its embeddings object, and the embeddings object
holds the API key it was built with. So a whole FAISS store must never be cached for all
visitors: whoever's key built it would be used for everyone's queries.

`SharedIndex` keeps only the key-free parts (the FAISS vectors, the stored chunks and the id
mapping, plus the manifest). Each session wraps them in its own FAISS object with its own
embeddings via `store_for`. The parts are only ever read; FAISS searches on a flat index are
safe to run from several threads at once.
"""

from dataclasses import dataclass
from typing import Any

from langchain_community.vectorstores import FAISS
from langchain_core.documents.base import Document
from langchain_core.embeddings import Embeddings

from src.config import Settings
from src.retrieval.vector_store import DISTANCE_STRATEGY, IndexManifest, load_vector_store


class _NoEmbeddings(Embeddings):
    """Placeholder used only while loading the files; it must never embed anything."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("The shared index has no embeddings; use SharedIndex.store_for().")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("The shared index has no embeddings; use SharedIndex.store_for().")


@dataclass(frozen=True)
class SharedIndex:
    """The key-free parts of a loaded index."""

    index: Any
    docstore: Any
    index_to_docstore_id: dict[int, str]
    manifest: IndexManifest

    def store_for(self, embeddings: Embeddings) -> FAISS:
        """A FAISS store over the shared data that embeds queries with `embeddings`."""
        return FAISS(
            embedding_function=embeddings,
            index=self.index,
            docstore=self.docstore,
            index_to_docstore_id=self.index_to_docstore_id,
            distance_strategy=DISTANCE_STRATEGY,
        )

    def chunk(self, chunk_id: str) -> Document:
        return self.docstore.search(chunk_id)


def load_shared_index(settings: Settings) -> SharedIndex:
    """Load the saved index's key-free parts (no embedding happens)."""
    store, manifest = load_vector_store(_NoEmbeddings(), settings)
    return SharedIndex(
        index=store.index,
        docstore=store.docstore,
        index_to_docstore_id=store.index_to_docstore_id,
        manifest=manifest,
    )
