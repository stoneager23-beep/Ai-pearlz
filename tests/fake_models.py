"""Deterministic stand-ins for OpenAI models, so tests never make network calls."""

import hashlib

import numpy as np
from langchain_core.embeddings import Embeddings

OPENAI_SMALL_DIMENSION = 1536


class HashEmbeddings(Embeddings):
    """Unit-length vectors derived from a hash of the text: equal texts give equal vectors.

    Not semantic: use it to test plumbing (persistence, caching, ids), never retrieval quality.
    """

    def __init__(self, dimension: int = OPENAI_SMALL_DIMENSION) -> None:
        self.dimension = dimension
        self.texts_embedded = 0

    def _vector(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        vector = np.random.default_rng(seed).normal(size=self.dimension)
        return (vector / np.linalg.norm(vector)).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.texts_embedded += len(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
