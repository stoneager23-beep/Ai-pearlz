"""Task 03 chunking experiment: which chunk size, overlap and strategy retrieve best?

Twelve configurations are compared on the same questions:

- format-blind recursive splitting of each file's raw text (the baseline), at 300, 800 and
  1500 characters, each with 0% and 15% overlap: six configurations;
- structure-aware splitting (the production loaders' page sections, heading sections and
  pricing rows, then recursive splitting inside them) at the same three sizes, 15% overlap;
- the same structure-aware splitting with a context header ("Document > section path") at the
  start of every chunk, added after the first run showed sections losing their parent heading.

For each: chunk count, mean and maximum length, longest chunk in tokens, hit@4 (how many
questions have a chunk that contains the answer among the top 4) and MRR (mean of 1/rank of
the first such chunk, 0 if none). Retrieval only; no LLM.

Usage:  python -m evaluation.experiments.chunking
Output: RESULTS_DIR/chunking_experiment.md
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from openai import OpenAIError

from evaluation.experiments.common import (
    markdown_table,
    run_timestamp,
    start_experiment,
    write_result,
)
from evaluation.retrieval_checks import RetrievalQuestion, first_hit_rank, load_retrieval_questions
from src.config import ConfigError, Settings
from src.ingestion.chunking import (
    ChunkStatistics,
    add_context_headers,
    chunk_statistics,
    split_into_chunks,
)
from src.ingestion.embedding_cache import CachedEmbedder, build_cached_embedder
from src.ingestion.loaders import DocxSectionLoader, load_knowledge_base, read_catalog
from src.ingestion.text_cleaning import collapse_whitespace
from src.retrieval.vector_store import create_vector_store
from src.utils.api_keys import ApiKeyError

RESULT_FILE = "chunking_experiment.md"
# The manual's measure: does a chunk containing the answer appear in the top 4?
TOP_K = 4
OVERLAP_SHARE = 0.15
SIZES = (300, 800, 1500)
FORMAT_BLIND = "recursive, format-blind"
STRUCTURE_AWARE = "structure-aware"
STRUCTURE_AWARE_HEADERS = "structure-aware + context header"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str
    chunk_size: int
    chunk_overlap: int


def experiment_configs() -> list[ChunkingConfig]:
    configs = [
        ChunkingConfig(FORMAT_BLIND, size, overlap)
        for size in SIZES
        for overlap in (0, round(size * OVERLAP_SHARE))
    ]
    configs += [
        ChunkingConfig(strategy, size, round(size * OVERLAP_SHARE))
        for strategy in (STRUCTURE_AWARE, STRUCTURE_AWARE_HEADERS)
        for size in SIZES
    ]
    return configs


@dataclass
class ConfigResult:
    config: ChunkingConfig
    statistics: ChunkStatistics
    ranks: dict[str, int | None] = field(default_factory=dict)

    def hits(self, questions: list[RetrievalQuestion]) -> int:
        return sum(self.ranks[question.id] is not None for question in questions)

    def mean_reciprocal_rank(self, questions: list[RetrievalQuestion]) -> float:
        reciprocal = [1 / rank for question in questions if (rank := self.ranks[question.id])]
        return sum(reciprocal) / len(questions)


def load_format_blind_documents(kb_dir: Path) -> list[Document]:
    """One Document per file with its raw text: no sections, no header stripping, no rows."""
    documents = []
    for name in read_catalog(kb_dir):
        path = kb_dir / name
        if path.suffix == ".pdf":
            text = PyPDFLoader(str(path), mode="single").load()[0].page_content
        elif path.suffix == ".docx":
            text = "\n".join(unit.page_content for unit in DocxSectionLoader(path).load())
        else:
            text = path.read_text(encoding="utf-8")
        documents.append(
            Document(page_content=collapse_whitespace(text), metadata={"source": name})
        )
    return documents


def evaluate_config(
    config: ChunkingConfig,
    units: list[Document],
    embedder: CachedEmbedder,
    questions: list[RetrievalQuestion],
    question_vectors: list[list[float]],
    embedding_model: str,
) -> ConfigResult:
    chunks = split_into_chunks(units, config.chunk_size, config.chunk_overlap)
    if config.strategy == STRUCTURE_AWARE_HEADERS:
        chunks = add_context_headers(chunks)
    store = create_vector_store(chunks, embedder.embeddings)
    result = ConfigResult(config, chunk_statistics(chunks, embedding_model))
    for question, vector in zip(questions, question_vectors, strict=True):
        ranked = [doc for doc, _ in store.similarity_search_with_score_by_vector(vector, k=TOP_K)]
        result.ranks[question.id] = first_hit_rank(question, ranked)
    logger.info(
        "%s %d/%d: %d chunks, hit@%d %d/%d",
        config.strategy,
        config.chunk_size,
        config.chunk_overlap,
        result.statistics.count,
        TOP_K,
        result.hits(questions),
        len(questions),
    )
    return result


def _overlap_label(config: ChunkingConfig) -> str:
    return f"{config.chunk_overlap} ({config.chunk_overlap / config.chunk_size:.0%})"


def render_results(
    results: list[ConfigResult],
    questions: list[RetrievalQuestion],
    embedder: CachedEmbedder,
    settings: Settings,
) -> str:
    samples = [question for question in questions if question.chunking_sample]
    summary_rows = [
        [
            result.config.strategy,
            str(result.config.chunk_size),
            _overlap_label(result.config),
            str(result.statistics.count),
            f"{result.statistics.mean_characters:.0f}",
            str(result.statistics.max_characters),
            str(result.statistics.max_tokens),
            f"**{result.hits(samples)}/{len(samples)}**",
            f"{result.hits(questions)}/{len(questions)}",
            f"{result.mean_reciprocal_rank(questions):.2f}",
        ]
        for result in results
    ]
    rank_rows = [
        [f"{result.config.strategy} {result.config.chunk_size}/{result.config.chunk_overlap}"]
        + [str(result.ranks[question.id] or "-") for question in questions]
        for result in results
    ]
    question_lines = [
        f"- **{question.id}**{' (sample)' if question.chunking_sample else ''}: {question.question}"
        for question in questions
    ]
    return "\n".join(
        [
            "# Chunking experiment (Task 03)",
            "",
            f"Run: {run_timestamp()}. Embedding model: `{settings.openai_embedding_model}`. "
            f"Retrieval: cosine similarity, top {TOP_K}. No LLM involved.",
            "",
            "## Results",
            "",
            markdown_table(
                [
                    "Strategy",
                    "Size (chars)",
                    "Overlap",
                    "Chunks",
                    "Mean chars",
                    "Max chars",
                    "Max tokens",
                    f"hit@{TOP_K}, 5 sample questions",
                    f"hit@{TOP_K}, all {len(questions)} questions",
                    f"MRR, all {len(questions)} questions",
                ],
                summary_rows,
            ),
            "",
            f'## Rank of the first chunk containing the answer ("-" = not in the top {TOP_K})',
            "",
            markdown_table(["Configuration"] + [question.id for question in questions], rank_rows),
            "",
            "## Questions",
            "",
            *question_lines,
            "",
            "A chunk contains the answer when it comes from an accepted source document and "
            "matches every answer pattern in `evaluation/retrieval_questions.json`.",
            "",
            f"Embedding cost of this run: {embedder.counter.texts_sent} texts and "
            f"{embedder.counter.tokens_sent:,} tokens sent to OpenAI (cache hits are free and not "
            "counted).",
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
    embedder = build_cached_embedder(context.api_key, settings)
    structured_units = load_knowledge_base(settings.knowledge_base_dir).documents
    raw_documents = load_format_blind_documents(settings.knowledge_base_dir)

    try:
        # text-embedding-3 models embed queries and documents the same way, so the questions go
        # through the cached document path once and the vectors are reused for every config.
        question_vectors = embedder.embeddings.embed_documents(
            [question.question for question in questions]
        )
        results = [
            evaluate_config(
                config,
                raw_documents if config.strategy == FORMAT_BLIND else structured_units,
                embedder,
                questions,
                question_vectors,
                settings.openai_embedding_model,
            )
            for config in experiment_configs()
        ]
    except OpenAIError as error:
        print(
            f"OpenAI request failed: {type(error).__name__}. Check your key and network.",
            file=sys.stderr,
        )
        return 1

    path = write_result(
        settings, RESULT_FILE, render_results(results, questions, embedder, settings)
    )
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
