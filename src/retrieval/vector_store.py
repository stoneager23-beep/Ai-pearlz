"""Create the FAISS vector store with one fixed similarity metric (Task 05).

Vectors are compared by inner product. OpenAI embeddings are unit length (measured in the
Task 04 diagnostic), and for unit vectors the inner product is exactly the cosine similarity:
1.0 means the same direction, 0 means unrelated. `assert_unit_length` checks this on the built
index, because if another model with unnormalised vectors were configured, scores would stop
being cosines and the calibrated relevance threshold would be meaningless.

Scores are always read with `similarity_search_with_score`, which returns that raw cosine
value. LangChain's `similarity_search_with_relevance_scores` is not used: for inner-product
stores it applies a conversion meant for distances, which distorts the scale the relevance
gate is calibrated on.
"""

import numpy as np
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

DISTANCE_STRATEGY = DistanceStrategy.MAX_INNER_PRODUCT
# How far a vector's length may be from 1.0 before inner product stops being a cosine.
UNIT_LENGTH_TOLERANCE = 1e-3


class NotUnitLengthError(ValueError):
    """The embedding model returned vectors that are not unit length."""


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
