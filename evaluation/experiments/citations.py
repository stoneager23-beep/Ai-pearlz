"""Task 10 evidence: are the citations shown with answers real and at the stated location?

Asks the ten retrieval questions (one per conversation) and checks every citation shown:

- the cited file is in the knowledge base;
- the snippet appears word for word in that file's text at the stated location (the PDF page
  and section, the document section, or the SKU's row), re-loaded from the source file, not
  from the index;
- no fabricated label survived (`invalid_citations` are dropped before display and counted).

Whether a snippet actually supports the answer is a human judgement; the table puts the
answer, the location and the snippet side by side so it can be checked quickly.

Usage:  python -m evaluation.experiments.citations
Output: RESULTS_DIR/citation_check.md
"""

import sys

from langchain_core.documents import Document

from evaluation.experiments.common import (
    markdown_table,
    run_timestamp,
    start_experiment,
    write_result,
)
from evaluation.retrieval_checks import load_retrieval_questions
from src.chains.schemas import Citation
from src.chains.session import SupportSession
from src.config import ConfigError
from src.errors import describe_failure
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import load_or_build
from src.ingestion.loaders import load_knowledge_base
from src.llm.clients import build_chat_model
from src.retrieval.locations import location_label
from src.utils.api_keys import ApiKeyError

RESULT_FILE = "citation_check.md"
ELLIPSIS = "..."


def _normalise(text: str) -> str:
    return " ".join(text.split())


def snippet_found_at_location(citation: Citation, units: list[Document]) -> bool:
    """True if the snippet occurs verbatim in a source unit with the citation's location."""
    snippet = _normalise(citation.snippet.removesuffix(ELLIPSIS))
    return any(
        unit.metadata["source"] == citation.source
        and location_label(unit.metadata) == citation.location
        and snippet in _normalise(unit.page_content)
        for unit in units
    )


def main() -> int:
    try:
        context = start_experiment()
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1
    settings = context.settings
    units = load_knowledge_base(settings.knowledge_base_dir).documents
    try:
        index = load_or_build(settings, build_cached_embedder(context.api_key, settings))
        chat_model = build_chat_model(context.api_key, settings)
        results = [
            (question, SupportSession(settings, index.store, chat_model).ask(question.question))
            for question in load_retrieval_questions()
        ]
    except Exception as error:  # an experiment run should end with a message, not a traceback
        print(describe_failure(error).message, file=sys.stderr)
        return 1

    rows = []
    shown = verified = fabricated = 0
    for question, response in results:
        fabricated += len(response.invalid_citations)
        if not response.sources:
            rows.append([question.id, question.question, response.answer, "(none)", "-", "-"])
        for citation in response.sources:
            found = snippet_found_at_location(citation, units)
            shown += 1
            verified += found
            rows.append(
                [
                    question.id,
                    question.question,
                    response.answer,
                    f"[{citation.number}] {citation.source}, {citation.location or '(opening)'}",
                    citation.snippet,
                    "yes" if found else "**no**",
                ]
            )
    cells = [[cell.replace("|", "/").replace("\n", " ") for cell in row] for row in rows]
    summary = (
        f"Citations shown: **{shown}**. Snippet found verbatim at the stated location: "
        f"**{verified}/{shown}**. Fabricated labels dropped before display: **{fabricated}**."
    )
    markdown = "\n".join(
        [
            "# Citation check (Task 10)",
            "",
            f"Run: {run_timestamp()}. Model `{settings.openai_chat_model}`.",
            "",
            summary,
            "",
            markdown_table(
                ["Q", "Question", "Answer", "Citation", "Snippet", "Verbatim at location"], cells
            ),
            "",
        ]
    )
    path = write_result(settings, RESULT_FILE, markdown)
    print(summary)
    print(f"Written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
