"""Retriever construction and the relevance gate (Task 06).

`ScoredRetriever` is a LangChain retriever (so it composes into the LCEL chain) over the FAISS
store. Unlike the stock `as_retriever()`, it keeps each chunk's cosine similarity, which the
relevance gate, the confidence signal and the logs all need. It returns copies of the stored
documents with the score added to their metadata; the documents inside the index are never
modified, which matters because the web app shares one index between all sessions.

The relevance gate is the pipeline-level refusal: if retrieval found nothing, or even the
best chunk's similarity is below RELEVANCE_THRESHOLD, the question is refused without calling
the chat model at all. The threshold is a property of this store, metric and embedding model,
calibrated on our own questions (`evaluation/experiments/threshold.py`), not a borrowed number.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from langchain_community.vectorstores import FAISS
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

from src.config import Settings

SCORE_KEY = "score"
ALL_PRODUCT_LINES = "all"

SearchType = Literal["similarity", "mmr"]
MetadataFilter = Callable[[Mapping[str, object]], bool]


class ScoredRetriever(BaseRetriever):
    """Top-k (or MMR) retrieval that records each chunk's cosine similarity in its metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    store: FAISS
    search_type: SearchType = "similarity"
    k: int = 4
    fetch_k: int = 20
    lambda_mult: float = 0.5
    doc_types: tuple[str, ...] = ()
    product_line: str | None = None

    def _matches(self, metadata: Mapping[str, object]) -> bool:
        if self.doc_types and metadata.get("doc_type") not in self.doc_types:
            return False
        if self.product_line is None:
            return True
        lines = metadata.get("product_lines") or []
        return self.product_line in lines or ALL_PRODUCT_LINES in lines

    def _metadata_filter(self) -> MetadataFilter | None:
        return self._matches if self.doc_types or self.product_line else None

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        metadata_filter = self._metadata_filter()
        if self.search_type == "mmr":
            pairs = self.store.max_marginal_relevance_search_with_score_by_vector(
                self.store.embeddings.embed_query(query),
                k=self.k,
                fetch_k=self.fetch_k,
                lambda_mult=self.lambda_mult,
                filter=metadata_filter,
            )
        else:
            pairs = self.store.similarity_search_with_score(
                query, k=self.k, fetch_k=self.fetch_k, filter=metadata_filter
            )
        return [
            Document(
                page_content=doc.page_content, metadata={**doc.metadata, SCORE_KEY: float(score)}
            )
            for doc, score in pairs
        ]


def build_retriever(
    store: FAISS,
    settings: Settings,
    *,
    doc_types: tuple[str, ...] = (),
    product_line: str | None = None,
) -> ScoredRetriever:
    """The retriever configured by RETRIEVAL_* settings, optionally restricted by metadata."""
    return ScoredRetriever(
        store=store,
        search_type=settings.retrieval_search_type,
        k=settings.retrieval_k,
        fetch_k=settings.retrieval_fetch_k,
        lambda_mult=settings.retrieval_mmr_lambda,
        doc_types=doc_types,
        product_line=product_line,
    )


@dataclass(frozen=True)
class GateDecision:
    """Whether retrieval found anything relevant enough to answer from, and why."""

    passed: bool
    best_score: float | None
    threshold: float
    reason: str


def relevance_gate(chunks: list[Document], threshold: float) -> GateDecision:
    """Refuse when nothing was retrieved or the best similarity is below `threshold`."""
    if not chunks:
        return GateDecision(False, None, threshold, "no chunks were retrieved")
    best = max(float(chunk.metadata[SCORE_KEY]) for chunk in chunks)
    if best < threshold:
        return GateDecision(
            False,
            best,
            threshold,
            f"best similarity {best:.3f} is below the threshold {threshold:.2f}",
        )
    return GateDecision(
        True, best, threshold, f"best similarity {best:.3f} meets the threshold {threshold:.2f}"
    )
