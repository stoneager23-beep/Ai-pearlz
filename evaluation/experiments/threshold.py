"""Task 06 threshold calibration: at what similarity should the pipeline refuse without the LLM?

For every calibration question, the best cosine similarity the production retriever finds is
recorded. Three groups are compared:

- answerable: the knowledge base has the answer, so the gate must let them through;
- gap: about Pearlz, but not answered by any document;
- off-topic: nothing to do with Pearlz.

A sweep shows, for each candidate threshold, how many questions of each group would pass. The
recommended threshold is the midpoint between the highest off-topic score and the lowest
answerable score, when those do not overlap, so neither side sits right on the line.

The gate is not expected to stop the gap questions: they are on-topic and land near real
content, so stopping them is the prompt's job (Task 08). The table makes that visible.

Usage:  python -m evaluation.experiments.threshold
Output: RESULTS_DIR/threshold_calibration.md
"""

import json
import sys
from pathlib import Path
from statistics import median

from evaluation.experiments.common import (
    markdown_table,
    run_timestamp,
    start_experiment,
    write_result,
)
from src.config import ConfigError
from src.errors import describe_failure
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import load_or_build
from src.retrieval.retriever import SCORE_KEY, build_retriever
from src.utils.api_keys import ApiKeyError

RESULT_FILE = "threshold_calibration.md"
QUESTIONS_FILE = Path(__file__).resolve().parent.parent / "threshold_questions.json"
GROUPS = ("answerable", "gap", "off_topic")
SWEEP_START = 0.10
SWEEP_STOP = 0.60
SWEEP_STEP = 0.025
# A threshold this close to the lowest answerable score would refuse a slightly reworded
# version of that question, so the recommendation must keep at least this margin below it.
MIN_MARGIN = 0.02


def sweep_values() -> list[float]:
    steps = round((SWEEP_STOP - SWEEP_START) / SWEEP_STEP)
    return [round(SWEEP_START + step * SWEEP_STEP, 3) for step in range(steps + 1)]


def recommend(scores: dict[str, list[tuple[str, float]]]) -> tuple[float, str]:
    lowest_answerable = min(score for _, score in scores["answerable"])
    highest_off_topic = max(score for _, score in scores["off_topic"])
    if highest_off_topic < lowest_answerable - MIN_MARGIN:
        threshold = round((highest_off_topic + lowest_answerable) / 2, 2)
        return threshold, (
            f"midpoint of the highest off-topic score ({highest_off_topic:.3f}) and the lowest "
            f"answerable score ({lowest_answerable:.3f})"
        )
    threshold = round(lowest_answerable - MIN_MARGIN, 2)
    return threshold, (
        f"off-topic and answerable scores overlap (highest off-topic {highest_off_topic:.3f}, "
        f"lowest answerable {lowest_answerable:.3f}), so the threshold sits just below the lowest "
        "answerable score: no answerable question is refused, and the prompt must catch the rest"
    )


def render(scores: dict[str, list[tuple[str, float]]], embedding_model: str) -> str:
    threshold, reason = recommend(scores)
    summary_rows = [
        [
            group,
            str(len(scores[group])),
            f"{min(s for _, s in scores[group]):.3f}",
            f"{median(s for _, s in scores[group]):.3f}",
            f"{max(s for _, s in scores[group]):.3f}",
        ]
        for group in GROUPS
    ]
    sweep_rows = []
    for value in sorted({*sweep_values(), threshold}):
        passing = {group: sum(score >= value for _, score in scores[group]) for group in GROUPS}
        marker = " **(recommended)**" if value == threshold else ""
        sweep_rows.append(
            [
                f"{value:.3f}{marker}",
                f"{passing['answerable']}/{len(scores['answerable'])}",
                f"{len(scores['gap']) - passing['gap']}/{len(scores['gap'])}",
                f"{len(scores['off_topic']) - passing['off_topic']}/{len(scores['off_topic'])}",
            ]
        )
    detail_rows = [
        [group, question, f"{score:.3f}"]
        for group in GROUPS
        for question, score in sorted(scores[group], key=lambda item: item[1])
    ]
    return "\n".join(
        [
            "# Relevance-gate threshold calibration (Task 06)",
            "",
            f"Run: {run_timestamp()}. Embedding model: `{embedding_model}`. Score: cosine "
            "similarity of the best retrieved chunk. Calibration questions are separate from "
            "the evaluation test set.",
            "",
            f"**Recommended threshold: {threshold:.2f}**, the {reason}.",
            "",
            "## Best-chunk similarity by group",
            "",
            markdown_table(["Group", "Questions", "Min", "Median", "Max"], summary_rows),
            "",
            "## Sweep",
            "",
            "Answerable: passed the gate (higher is better). Gap and off-topic: refused by the "
            "gate.",
            "",
            markdown_table(
                ["Threshold", "Answerable passed", "Gap refused", "Off-topic refused"], sweep_rows
            ),
            "",
            "## Every question",
            "",
            markdown_table(["Group", "Question", "Best similarity"], detail_rows),
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
    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    try:
        index = load_or_build(settings, build_cached_embedder(context.api_key, settings))
        retriever = build_retriever(index.store, settings)
        scores = {
            group: [
                (question, max(doc.metadata[SCORE_KEY] for doc in retriever.invoke(question)))
                for question in questions[group]
            ]
            for group in GROUPS
        }
    except Exception as error:  # an experiment run should end with a message, not a traceback
        print(describe_failure(error).message, file=sys.stderr)
        return 1

    path = write_result(settings, RESULT_FILE, render(scores, settings.openai_embedding_model))
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
