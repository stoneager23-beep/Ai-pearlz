"""Task 04 embedding diagnostic: what the vectors look like and what cosine similarity says.

Embeds two paraphrases and one unrelated sentence and prints their pairwise cosine
similarities (the manual's check), plus:

- the measured vector dimension and length (OpenAI vectors should be unit length, which is why
  the index can use inner product as cosine similarity);
- a pair that looks alike but means something different ("E-03" vs "E-08"), which shows where
  semantic search is weaker than keyword search (viva Q3);
- the longest production chunk in tokens against the model's input limit (manual mistake #11).

Usage:  python -m evaluation.experiments.embedding_diagnostic
Output: RESULTS_DIR/embedding_diagnostic.md
"""

import sys
from itertools import combinations

import numpy as np
from openai import OpenAIError

from evaluation.experiments.common import (
    markdown_table,
    run_timestamp,
    start_experiment,
    write_result,
)
from src.config import EMBEDDING_SPLIT_LIMIT_TOKENS, ConfigError
from src.ingestion.chunking import build_chunks, chunk_statistics
from src.ingestion.loaders import load_knowledge_base
from src.llm.clients import build_embeddings
from src.utils.api_keys import ApiKeyError

RESULT_FILE = "embedding_diagnostic.md"

SENTENCES = {
    "A (customer words)": "My purifier keeps beeping three times and the light is flashing red.",
    "B (manual words)": "The unit sounds a triple short tone and its FILTER indicator pulses red.",
    "C (unrelated)": "Next-day delivery is offered in Karachi, Lahore and Islamabad.",
}
LOOK_ALIKE = {
    "D": "Alert E-03 is shown on the display.",
    "E": "Alert E-08 is shown on the display.",
}


def cosine(first: list[float], second: list[float]) -> float:
    a, b = np.asarray(first), np.asarray(second)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def main() -> int:
    try:
        context = start_experiment()
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1
    settings = context.settings
    texts = {**SENTENCES, **LOOK_ALIKE}
    try:
        vectors = dict(
            zip(
                texts,
                build_embeddings(context.api_key, settings).embed_documents(list(texts.values())),
                strict=True,
            )
        )
    except OpenAIError as error:
        print(
            f"OpenAI request failed: {type(error).__name__}. Check your key and network.",
            file=sys.stderr,
        )
        return 1

    dimensions = {len(vector) for vector in vectors.values()}
    lengths = [float(np.linalg.norm(vector)) for vector in vectors.values()]
    pair_rows = [
        [f"{first} / {second}", f"{cosine(vectors[first], vectors[second]):.3f}"]
        for first, second in combinations(SENTENCES, 2)
    ]
    look_alike_similarity = cosine(vectors["D"], vectors["E"])

    chunks = build_chunks(load_knowledge_base(settings.knowledge_base_dir).documents, settings)
    statistics = chunk_statistics(chunks, settings.openai_embedding_model)
    spec = settings.embedding_spec

    markdown = "\n".join(
        [
            "# Embedding diagnostic (Task 04)",
            "",
            f"Run: {run_timestamp()}.",
            "",
            "## The model",
            "",
            markdown_table(
                ["Property", "Value"],
                [
                    ["Model", f"`{spec.name}`"],
                    ["Vector dimension (measured)", ", ".join(str(d) for d in sorted(dimensions))],
                    ["Vector dimension (documented)", str(spec.dimension)],
                    [
                        "Vector length, min to max (measured)",
                        f"{min(lengths):.4f} to {max(lengths):.4f}",
                    ],
                    ["Maximum input (documented)", f"{spec.max_input_tokens:,} tokens"],
                    [
                        "LangChain splits inputs longer than",
                        f"{EMBEDDING_SPLIT_LIMIT_TOKENS:,} tokens",
                    ],
                    [
                        "Longest production chunk",
                        f"{statistics.max_tokens} tokens ({statistics.max_characters} characters), "
                        f"chunk size {settings.chunk_size}",
                    ],
                ],
            ),
            "",
            "## Paraphrases versus an unrelated sentence",
            "",
            *[f"- **{label}**: {text}" for label, text in SENTENCES.items()],
            "",
            markdown_table(["Pair", "Cosine similarity"], pair_rows),
            "",
            "## Look-alike codes with different meanings",
            "",
            *[f"- **{label}**: {text}" for label, text in LOOK_ALIKE.items()],
            "",
            f"Cosine similarity D / E: **{look_alike_similarity:.3f}**. E-03 is a saturated "
            "pre-filter and E-08 a display fault, yet the sentences are almost identical as "
            "vectors. Exact identifiers are where keyword search beats semantic search.",
            "",
        ]
    )
    path = write_result(settings, RESULT_FILE, markdown)
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
