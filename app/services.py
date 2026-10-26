"""Connects the interface to the system: the shared index and each visitor's own session.

Multi-user safety. `st.cache_resource` is shared by every visitor of the deployed app, so the
only thing cached here is `SharedIndex`: FAISS vectors, chunks and the manifest, with no API key
and no client. Each visitor's chat model and query embeddings are built from the key in their
own `st.session_state` (`build_user_session`), and are never cached.
"""

import hashlib

import streamlit as st

from src.chains.session import SupportSession, build_user_session
from src.config import Settings
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import IndexSyncResult, sync_index
from src.ingestion.loaders import read_catalog
from src.llm.clients import build_chat_model
from src.retrieval.shared_index import SharedIndex, load_shared_index
from src.retrieval.vector_store import manifest_path

# One index is in use at a time; after a rebuild the previous one is dropped from memory.
_SHARED_INDEX_ENTRIES = 1


def index_version(settings: Settings) -> str:
    """Identifies the saved index; it changes whenever the index is rebuilt or updated."""
    return hashlib.sha256(manifest_path(settings).read_bytes()).hexdigest()


@st.cache_resource(max_entries=_SHARED_INDEX_ENTRIES, show_spinner=False)
def shared_index(_settings: Settings, version: str) -> SharedIndex:
    """Key-free index data, loaded once per index version and shared by all sessions."""
    return load_shared_index(_settings)


def build_index_with_key(settings: Settings, api_key: str) -> IndexSyncResult:
    """Build or update the saved index with the visitor's key, behind the build lock.

    Manual deviation 2: the deployed app has no key of its own, so the first visitor's
    validated key embeds the knowledge base. Concurrent visitors wait on the file lock in
    `sync_index`, and then find the index up to date instead of building it again.
    """
    return sync_index(settings, build_cached_embedder(api_key, settings))


def new_support_session(
    settings: Settings,
    index: SharedIndex,
    api_key: str,
    model_name: str,
    *,
    doc_types: tuple[str, ...] = (),
    product_line: str | None = None,
) -> SupportSession:
    """A session for this visitor only: their key, their clients, their memory."""
    return build_user_session(
        settings,
        index,
        api_key,
        model_name,
        streaming=True,
        doc_types=doc_types,
        product_line=product_line,
    )


def switch_model(
    session: SupportSession, settings: Settings, api_key: str, model_name: str
) -> None:
    session.set_chat_model(build_chat_model(api_key, settings, model_name, streaming=True))


def product_lines(settings: Settings) -> list[str]:
    """Product lines named in the catalogue ("all" means a document covers every product)."""
    names = {
        line
        for entry in read_catalog(settings.knowledge_base_dir).values()
        for line in entry.product_lines
        if line != "all"
    }
    return sorted(names)


def doc_types(settings: Settings) -> list[str]:
    return sorted(
        {str(entry.doc_type) for entry in read_catalog(settings.knowledge_base_dir).values()}
    )
