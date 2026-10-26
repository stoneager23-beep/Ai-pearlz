"""Task 06 retriever comparison: which retrieval policy finds the answer most reliably?

Every strategy runs over the same persisted index and the same ten retrieval questions
(`evaluation/retrieval_questions.json`), using the production `ScoredRetriever`:

- similarity search with k = 3, 4 and 8;
- maximal marginal relevance (MMR) with k = 4 and 8 (fetch_k 20, lambda 0.5);
- similarity k = 8, then dropping chunks below RELEVANCE_THRESHOLD (a score-threshold policy);
- similarity k = 4 restricted to the question's own document type. The type is taken from the
  ground truth, so this is an upper bound on what automatic routing (bonus C3) could gain.

Metrics: hit@k (a chunk containing the answer was returned), MRR (1/rank of the first such
chunk), the average number of distinct documents returned (diversity) and the average number
of chunks handed on. Retrieval only; no LLM.

Usage:  python -m evaluation.experiments.retrievers
Output: RESULTS_DIR/retriever_comparison.md
"""

import sys
import time
from dataclasses import dataclass, field
from statistics import mean

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from evaluation.experiments.common import (
    markdown_table,
    run_timestamp,
    start_experiment,
    write_result,
)
from evaluation.retrieval_checks import RetrievalQuestion, first_hit_rank, load_retrieval_questions
from src.config import ConfigError, Settings
from src.errors import describe_failure
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import load_or_build
from src.ingestion.loaders import read_catalog
from src.retrieval.retriever import SCORE_KEY, ScoredRetriever, SearchType
from src.utils.api_keys import ApiKeyError

RESULT_FILE = "retriever_comparison.md"
MMR_FETCH_K = 20
MMR_LAMBDA = 0.5
MILLISECONDS = 1000


@dataclass(frozen=True)
class Strategy:
    name: str
    search_type: SearchType
    k: int
    apply_threshold: bool = False
    filter_by_doc_type: bool = False


STRATEGIES = (
    Strategy("similarity, k=3", "similarity", 3),
    Strategy("similarity, k=4", "similarity", 4),
    Strategy("similarity, k=8", "similarity", 8),
    Strategy("MMR, k=4", "mmr", 4),
    Strategy("MMR, k=8", "mmr", 8),
    Strategy("similarity, k=8, threshold filter", "similarity", 8, apply_threshold=True),
    Strategy("similarity, k=4, doc_type filter (oracle)", "similarity", 4, filter_by_doc_type=True),
)


@dataclass
class StrategyResult:
    strategy: Strategy
    ranks: dict[str, int | None] = field(default_factory=dict)
    distinct_documents: list[int] = field(default_factory=list)
    chunks_returned: list[int] = field(default_factory=list)
    milliseconds: list[float] = field(default_factory=list)

    def hits(self) -> int:
        return sum(rank is not None for rank in self.ranks.values())

    def mrr(self) -> float:
        return sum(1 / rank for rank in self.ranks.values() if rank) / len(self.ranks)


def run_strategy(
    strategy: Strategy,
    store: FAISS,
    settings: Settings,
    questions: list[RetrievalQuestion],
    doc_type_of: dict[str, str],
) -> StrategyResult:
    result = StrategyResult(strategy)
    for question in questions:
        doc_types = (
            (doc_type_of[question.accepted_sources[0]],) if strategy.filter_by_doc_type else ()
        )
        retriever = ScoredRetriever(
            store=store,
            search_type=strategy.search_type,
            k=strategy.k,
            fetch_k=MMR_FETCH_K,
            lambda_mult=MMR_LAMBDA,
            doc_types=doc_types,
        )
        started = time.perf_counter()
        chunks: list[Document] = retriever.invoke(question.question)
        result.milliseconds.append((time.perf_counter() - started) * MILLISECONDS)
        if strategy.apply_threshold:
            chunks = [c for c in chunks if c.metadata[SCORE_KEY] >= settings.relevance_threshold]
        result.ranks[question.id] = first_hit_rank(question, chunks)
        result.distinct_documents.append(len({chunk.metadata["source"] for chunk in chunks}))
        result.chunks_returned.append(len(chunks))
    return result


def render(
    results: list[StrategyResult], questions: list[RetrievalQuestion], settings: Settings
) -> str:
    summary_rows = [
        [
            result.strategy.name,
            f"**{result.hits()}/{len(questions)}**",
            f"{result.mrr():.2f}",
            f"{mean(result.distinct_documents):.1f}",
            f"{mean(result.chunks_returned):.1f}",
            f"{mean(result.milliseconds):.0f}",
        ]
        for result in results
    ]
    rank_rows = [
        [result.strategy.name] + [str(result.ranks[question.id] or "-") for question in questions]
        for result in results
    ]
    return "\n".join(
        [
            "# Retriever comparison (Task 06)",
            "",
            f"Run: {run_timestamp()}. Embedding model: `{settings.openai_embedding_model}`. "
            f"Index: chunk size {settings.chunk_size}, overlap {settings.chunk_overlap}, context "
            f"headers {settings.chunk_context_headers}. Threshold filter uses "
            f"RELEVANCE_THRESHOLD = {settings.relevance_threshold}. No LLM involved.",
            "",
            markdown_table(
                [
                    "Strategy",
                    "hit@k (10 questions)",
                    "MRR",
                    "Distinct documents returned",
                    "Chunks handed on",
                    "Mean latency (ms, incl. query embedding)",
                ],
                summary_rows,
            ),
            "",
            '## Rank of the first chunk containing the answer ("-" = not returned)',
            "",
            markdown_table(["Strategy"] + [question.id for question in questions], rank_rows),
            "",
            *[f"- **{question.id}**: {question.question}" for question in questions],
            "",
        ]
    )


def main() -> int:
    try:
        context = start_experiment()
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1
    settings = context.settings
    questions = load_retrieval_questions()
    doc_type_of = {
        name: entry.doc_type for name, entry in read_catalog(settings.knowledge_base_dir).items()
    }
    try:
        index = load_or_build(settings, build_cached_embedder(context.api_key, settings))
        results = [
            run_strategy(strategy, index.store, settings, questions, doc_type_of)
            for strategy in STRATEGIES
        ]
    except Exception as error:  # an experiment run should end with a message, not a traceback
        print(describe_failure(error).message, file=sys.stderr)
        return 1

    path = write_result(settings, RESULT_FILE, render(results, questions, settings))
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
