"""Direct similarity search over the persisted index: the debugging tool of Task 05.

Usage:  python -m src.retrieval.search "how long is the warranty" [--k 5]

Prints, for each hit, its cosine similarity, chunk id, source document and location, and the
first characters of the chunk. Loads the saved index (building it first only if needed); only
the query itself is embedded.
"""

import argparse
import logging
import sys
import textwrap

from src.config import DEFAULT_ENV_FILE, ConfigError, get_settings
from src.errors import describe_failure, log_detail
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import load_or_build
from src.retrieval.locations import location_label
from src.utils.api_keys import ApiKeyError, interactive_prompt, resolve_cli_api_key
from src.utils.logging_setup import configure_logging

PREVIEW_CHARACTERS = 200

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Similarity search over the SupportPearlz index.")
    parser.add_argument("query", help="The text to search for")
    parser.add_argument("--k", type=int, default=None, help="Number of hits (default: RETRIEVAL_K)")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        configure_logging(settings)
        api_key = resolve_cli_api_key(DEFAULT_ENV_FILE, prompt=interactive_prompt())
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1

    k = args.k or settings.retrieval_k
    try:
        index = load_or_build(settings, build_cached_embedder(api_key, settings))
        hits = index.store.similarity_search_with_score(args.query, k=k)
    except Exception as error:  # the command's last line of defence: never show a traceback
        logger.error("Search failed: %s", log_detail(error), exc_info=True)
        print(f"Search failed. {describe_failure(error).message}", file=sys.stderr)
        return 1

    print(f'Top {k} chunks for "{args.query}" (cosine similarity):\n')
    for rank, (chunk, score) in enumerate(hits, start=1):
        text = chunk.page_content.removeprefix(chunk.metadata.get("context_header", "")).strip()
        preview = textwrap.shorten(" ".join(text.split()), PREVIEW_CHARACTERS, placeholder="...")
        print(f"{rank}. {score:.3f}  {chunk.metadata['chunk_id']}")
        print(f"   {chunk.metadata['source']}  {location_label(chunk.metadata)}")
        print(f"   {preview}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
