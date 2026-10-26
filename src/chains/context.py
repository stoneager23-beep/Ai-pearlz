"""Turn retrieved chunks into the labelled context the model reads (Task 07).

Each chunk becomes one block:

    [S2] Warranty Policy (warranty_policy.md), §3.2 Exclusions; version 3.1, updated 2026-04-01
    <chunk text>

The label ([S2]) is how the model cites a block, and how `citations.resolve_citations` maps a
citation back to a document and location. The version and date let the model tell an older
statement from a newer one (the E-06 firmware change).

A budget of MAX_CONTEXT_CHARACTERS caps how much retrieved text goes into one prompt. Chunks
arrive best first, so when the budget runs out the weakest chunks are dropped, and that is
logged. The first chunk is always kept: if the gate passed, the model must see something.
"""

import logging
from dataclasses import dataclass, field

from langchain_core.documents import Document

from src.retrieval.locations import location_label

LABEL_PREFIX = "S"
BLOCK_SEPARATOR = "\n\n"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextBundle:
    """The context text and the label of every chunk in it."""

    text: str
    chunks_by_label: dict[str, Document]
    dropped_chunk_ids: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return bool(self.dropped_chunk_ids)


def chunk_body(chunk: Document) -> str:
    """The chunk text without its "Document > section" header line (the block header says it)."""
    header = chunk.metadata.get("context_header")
    text = chunk.page_content
    if header and text.startswith(header):
        text = text[len(header) :]
    return text.strip()


def block_header(label: str, chunk: Document) -> str:
    metadata = chunk.metadata
    location = location_label(metadata)
    where = f", {location}" if location else ""
    return (
        f"[{label}] {metadata['doc_title']} ({metadata['source']}){where}; "
        f"version {metadata['version']}, updated {metadata['last_updated']}"
    )


def build_context(chunks: list[Document], max_characters: int) -> ContextBundle:
    """Label chunks [S1]..[Sk] in retrieval order and join them within the character budget."""
    blocks: list[str] = []
    chunks_by_label: dict[str, Document] = {}
    dropped: list[str] = []
    used = 0
    for chunk in chunks:
        label = f"{LABEL_PREFIX}{len(blocks) + 1}"
        block = f"{block_header(label, chunk)}\n{chunk_body(chunk)}"
        if blocks and used + len(BLOCK_SEPARATOR) + len(block) > max_characters:
            dropped.append(chunk.metadata["chunk_id"])
            continue
        blocks.append(block)
        chunks_by_label[label] = chunk
        used += len(block) + (len(BLOCK_SEPARATOR) if len(blocks) > 1 else 0)
    if dropped:
        logger.info("Context budget of %d characters reached; dropped %s", max_characters, dropped)
    return ContextBundle(BLOCK_SEPARATOR.join(blocks), chunks_by_label, dropped)
