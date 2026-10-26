"""Create, persist and load the FAISS vector store (Task 05).

Similarity: vectors are compared by inner product. OpenAI embeddings are unit length (measured
in the Task 04 diagnostic), and for unit vectors the inner product is exactly the cosine
similarity: 1.0 means the same direction, 0 means unrelated. `assert_unit_length` checks this
on every built index, because unnormalised vectors from another model would make the scores
stop being cosines and the calibrated relevance threshold meaningless.

Scores are always read with `similarity_search_with_score`, which returns that raw cosine.
LangChain's `similarity_search_with_relevance_scores` is not used: for inner-product stores it
applies a conversion meant for distances, which distorts the scale the gate is calibrated on.

On disk, an index is three files in VECTOR_STORE_DIR: `<collection>.faiss` (the vectors),
`<collection>.pkl` (chunk texts and metadata) and `<collection>.manifest.json` (what built it).
The manifest is what makes loading safe: an index built with another embedding model, other
chunk settings or for a different knowledge base is never silently used.
"""

import logging
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, ValidationError

from src.config import Settings

DISTANCE_STRATEGY = DistanceStrategy.MAX_INNER_PRODUCT
# How far a vector's length may be from 1.0 before inner product stops being a cosine.
UNIT_LENGTH_TOLERANCE = 1e-3
MANIFEST_SUFFIX = ".manifest.json"

logger = logging.getLogger(__name__)


class VectorStoreError(Exception):
    """Base class for problems with the persisted index. Messages are user-facing."""


class MissingIndexError(VectorStoreError):
    """No persisted index exists yet."""


class IndexMismatchError(VectorStoreError):
    """The persisted index was built with different settings or is damaged."""


class NotUnitLengthError(ValueError):
    """The embedding model returned vectors that are not unit length."""


class IndexManifest(BaseModel):
    """Everything needed to decide whether a persisted index can be used as it is."""

    collection_name: str
    embedding_model: str
    embedding_dimension: int
    embedding_max_input_tokens: int
    chunk_size: int
    chunk_overlap: int
    chunk_context_headers: bool
    file_fingerprints: dict[str, str]
    chunk_ids_by_source: dict[str, list[str]]
    chunk_count: int
    built_at: datetime
    library_versions: dict[str, str]

    def problems_with(self, settings: Settings) -> list[str]:
        """Why this index cannot serve the current settings (empty if it can)."""
        expected = {
            "embedding model": (self.embedding_model, settings.openai_embedding_model),
            "embedding dimension": (self.embedding_dimension, settings.embedding_spec.dimension),
            "chunk size": (self.chunk_size, settings.chunk_size),
            "chunk overlap": (self.chunk_overlap, settings.chunk_overlap),
            "context headers": (self.chunk_context_headers, settings.chunk_context_headers),
        }
        return [
            f"{name}: index has {built}, settings say {configured}"
            for name, (built, configured) in expected.items()
            if built != configured
        ]


def new_manifest(
    settings: Settings,
    file_fingerprints: dict[str, str],
    chunk_ids_by_source: dict[str, list[str]],
) -> IndexManifest:
    return IndexManifest(
        collection_name=settings.collection_name,
        embedding_model=settings.openai_embedding_model,
        embedding_dimension=settings.embedding_spec.dimension,
        embedding_max_input_tokens=settings.embedding_spec.max_input_tokens,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        chunk_context_headers=settings.chunk_context_headers,
        file_fingerprints=file_fingerprints,
        chunk_ids_by_source=chunk_ids_by_source,
        chunk_count=sum(len(ids) for ids in chunk_ids_by_source.values()),
        built_at=datetime.now(UTC),
        library_versions={name: version(name) for name in ("faiss-cpu", "langchain-community")},
    )


def create_vector_store(chunks: list[Document], embeddings: Embeddings) -> FAISS:
    """Embed `chunks` and index them in memory, keyed by their chunk ids."""
    return FAISS.from_documents(
        chunks,
        embeddings,
        ids=[chunk.metadata["chunk_id"] for chunk in chunks],
        distance_strategy=DISTANCE_STRATEGY,
    )


def assert_unit_length(store: FAISS) -> None:
    """Check that every indexed vector has length 1, so scores are cosine similarities."""
    vectors = store.index.reconstruct_n(0, store.index.ntotal)
    lengths = np.linalg.norm(vectors, axis=1)
    worst = float(np.max(np.abs(lengths - 1.0))) if len(lengths) else 0.0
    if worst > UNIT_LENGTH_TOLERANCE:
        raise NotUnitLengthError(
            f"Embedding vectors are not unit length (largest deviation {worst:.4f}); "
            "scores would not be cosine similarities."
        )


def manifest_path(settings: Settings) -> Path:
    return settings.vector_store_dir / f"{settings.collection_name}{MANIFEST_SUFFIX}"


def read_manifest(settings: Settings) -> IndexManifest:
    path = manifest_path(settings)
    if not path.is_file():
        raise MissingIndexError(
            "No index has been built yet. Run: python -m src.ingestion.build_index"
        )
    try:
        return IndexManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise IndexMismatchError(
            f"The index manifest is damaged ({error.error_count()} errors)."
        ) from error


def save_vector_store(store: FAISS, manifest: IndexManifest, settings: Settings) -> None:
    """Write the index files, then the manifest last, so a manifest always describes them."""
    settings.vector_store_dir.mkdir(parents=True, exist_ok=True)
    store.save_local(str(settings.vector_store_dir), index_name=settings.collection_name)
    path = manifest_path(settings)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(manifest.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    temporary.replace(path)
    logger.info(
        "Saved index %s: %d chunks, model %s",
        settings.collection_name,
        manifest.chunk_count,
        manifest.embedding_model,
    )


def load_vector_store(embeddings: Embeddings, settings: Settings) -> tuple[FAISS, IndexManifest]:
    """Load the persisted index for querying, refusing one that does not match the settings.

    `embeddings` is used only to embed queries; nothing is re-embedded when loading.
    """
    manifest = read_manifest(settings)
    problems = manifest.problems_with(settings)
    if problems:
        raise IndexMismatchError(
            "The saved index was built with different settings ("
            + "; ".join(problems)
            + "). Rebuild it: python -m src.ingestion.build_index --rebuild"
        )
    # The .pkl file is a Python pickle. It is only ever loaded from our own VECTOR_STORE_DIR,
    # written by save_vector_store; never point VECTOR_STORE_DIR at files from elsewhere.
    store = FAISS.load_local(
        str(settings.vector_store_dir),
        embeddings,
        index_name=settings.collection_name,
        allow_dangerous_deserialization=True,
        distance_strategy=DISTANCE_STRATEGY,
    )
    if store.index.ntotal != manifest.chunk_count or store.index.d != manifest.embedding_dimension:
        raise IndexMismatchError(
            "The saved index files do not match their manifest; rebuild with --rebuild."
        )
    logger.info(
        "Loaded index %s from disk: %d chunks, model %s, built %s (no embeddings computed)",
        settings.collection_name,
        manifest.chunk_count,
        manifest.embedding_model,
        manifest.built_at.isoformat(timespec="seconds"),
    )
    return store, manifest


def describe_manifest(manifest: IndexManifest) -> dict[str, str]:
    """A small, display-friendly summary (used by the CLI and the web app)."""
    return {
        "Documents": str(len(manifest.file_fingerprints)),
        "Chunks": str(manifest.chunk_count),
        "Embedding model": f"{manifest.embedding_model} ({manifest.embedding_dimension} dims)",
        "Last built": manifest.built_at.strftime("%Y-%m-%d %H:%M UTC"),
    }
