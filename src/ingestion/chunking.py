"""Split loaded documents into chunks for embedding (Task 03).

The loaders already produce one Document per structural unit (a page section, a heading
section or a pricing row). Chunking only splits units that are longer than CHUNK_SIZE, using
LangChain's RecursiveCharacterTextSplitter, which prefers to break at paragraph, then line,
then word boundaries. The splitter copies each unit's metadata to every chunk it produces, so
source, section, page and SKU survive splitting (manual mistake #2).

Each chunk gets a readable, stable id such as "warranty_policy.md::0007", which appears in logs,
in the "Behind the answer" panel and in the evaluation results.
"""

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import EMBEDDING_SPLIT_LIMIT_TOKENS, Settings
from src.ingestion.embedding_cache import count_tokens

CHUNK_ID_SEPARATOR = "::"


class ChunkTooLongError(ValueError):
    """A chunk would exceed the embedding model's input limit and be silently split."""


@dataclass(frozen=True)
class ChunkStatistics:
    count: int
    mean_characters: float
    max_characters: int
    max_tokens: int


def split_into_chunks(units: list[Document], chunk_size: int, chunk_overlap: int) -> list[Document]:
    """Split units longer than `chunk_size` characters; give every chunk a stable id."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )
    chunks = splitter.split_documents(units)
    per_source: dict[str, int] = defaultdict(int)
    for chunk in chunks:
        source = chunk.metadata["source"]
        chunk.metadata["chunk_id"] = f"{source}{CHUNK_ID_SEPARATOR}{per_source[source]:04d}"
        per_source[source] += 1
    return chunks


def context_header(metadata: dict) -> str:
    """The line "Document title > section path" for a chunk ("Pricing Guide > SKU" for prices)."""
    location = metadata.get("section_path") or metadata.get("section") or metadata.get("sku")
    title = metadata["doc_title"]
    return f"{title} > {location}" if location and location != title else title


def add_context_headers(chunks: list[Document]) -> list[Document]:
    """Start every chunk with a line naming its document and section path.

    A chunk cut from deep inside a section loses the words of its parent headings: the
    privacy policy's "3.2 Water-usage and device telemetry" never says "app" itself. The header
    puts that context back into the text that is embedded and shown to the model. The header is
    also stored in metadata, so citation snippets can leave it out.
    """
    with_headers = []
    for chunk in chunks:
        header = context_header(chunk.metadata)
        metadata = {**chunk.metadata, "context_header": header}
        with_headers.append(
            Document(page_content=f"{header}\n{chunk.page_content}", metadata=metadata)
        )
    return with_headers


def chunk_statistics(chunks: list[Document], embedding_model: str) -> ChunkStatistics:
    """Counts and sizes of a chunk set, including the longest chunk in tokens."""
    lengths = [len(chunk.page_content) for chunk in chunks]
    return ChunkStatistics(
        count=len(chunks),
        mean_characters=mean(lengths) if lengths else 0.0,
        max_characters=max(lengths, default=0),
        max_tokens=max(
            (count_tokens(chunk.page_content, embedding_model) for chunk in chunks), default=0
        ),
    )


def build_chunks(units: list[Document], settings: Settings) -> list[Document]:
    """The production chunking used by the index build: split, add headers, check lengths."""
    chunks = split_into_chunks(units, settings.chunk_size, settings.chunk_overlap)
    if settings.chunk_context_headers:
        chunks = add_context_headers(chunks)
    assert_within_embedding_limit(chunks, settings.openai_embedding_model)
    return chunks


def assert_within_embedding_limit(chunks: list[Document], embedding_model: str) -> None:
    """Refuse chunks the embedding step would silently split and average (manual mistake #11)."""
    for chunk in chunks:
        tokens = count_tokens(chunk.page_content, embedding_model)
        if tokens > EMBEDDING_SPLIT_LIMIT_TOKENS:
            raise ChunkTooLongError(
                f"{chunk.metadata['chunk_id']} has {tokens} tokens; the limit is "
                f"{EMBEDDING_SPLIT_LIMIT_TOKENS}. Lower CHUNK_SIZE."
            )
