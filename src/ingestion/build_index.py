"""Build or update the persisted vector index: the one documented build command (Tasks 04-05).

Usage:
    python -m src.ingestion.build_index            # build if missing, else update what changed
    python -m src.ingestion.build_index --rebuild  # rebuild everything from scratch

The OpenAI key comes from OPENAI_API_KEY in the environment or .env, or a hidden prompt.
Embeddings are cached, so a rebuild only pays for chunks whose text has never been embedded.
"""

import argparse
import logging
import sys

from src.config import DEFAULT_ENV_FILE, ConfigError, get_settings
from src.errors import describe_failure, log_detail
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import IndexSyncResult, sync_index
from src.retrieval.vector_store import manifest_path
from src.utils.api_keys import ApiKeyError, interactive_prompt, resolve_cli_api_key
from src.utils.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def render_summary(result: IndexSyncResult, index_location: str) -> str:
    lines = [
        f"Index {result.mode} ({result.reason}).",
        f"  Files added: {len(result.added)}, changed: {len(result.changed)}, "
        f"removed: {len(result.removed)}",
        f"  Chunks removed: {result.chunks_removed}, added: {result.chunks_added}, "
        f"now in index: {result.chunk_count}",
        f"  Sent to OpenAI for embedding: {result.texts_embedded} chunks, "
        f"{result.tokens_embedded:,} tokens (cached chunks are free)",
        f"  Time: {result.seconds:.1f}s",
        f"  Index: {index_location}",
    ]
    for report in result.skipped_files:
        lines.append(f"  Skipped {report.file_name}: {report.reason}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or update the SupportPearlz index.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild everything from scratch")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        configure_logging(settings)
        api_key = resolve_cli_api_key(DEFAULT_ENV_FILE, prompt=interactive_prompt())
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1

    try:
        result = sync_index(
            settings, build_cached_embedder(api_key, settings), rebuild=args.rebuild
        )
    except Exception as error:  # the command's last line of defence: never show a traceback
        logger.error("Index build failed: %s", log_detail(error), exc_info=True)
        print(f"Index build failed. {describe_failure(error).message}", file=sys.stderr)
        return 1

    print(render_summary(result, str(manifest_path(settings).parent)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
