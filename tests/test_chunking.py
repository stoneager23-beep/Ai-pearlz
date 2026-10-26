"""Chunk metadata survives splitting, ids are stable, and over-long chunks are refused (Task 03)."""

import pytest
from langchain_core.documents import Document

from src.config import get_settings, load_settings
from src.ingestion.chunking import (
    ChunkTooLongError,
    add_context_headers,
    assert_within_embedding_limit,
    build_chunks,
    chunk_statistics,
    context_header,
    split_into_chunks,
)
from src.ingestion.loaders import load_knowledge_base

CONTRACT_KEYS = {"source", "doc_type", "product_lines", "version", "last_updated", "doc_title"}


def _unit(text: str, **metadata) -> Document:
    base = {
        "source": "policy.md",
        "doc_title": "Refund Policy",
        "doc_type": "policy",
        "product_lines": ["all"],
        "version": "1",
        "last_updated": "2026-01-01",
        "section": "2.1 Opened items",
        "section_path": "2. Condition > 2.1 Opened items",
    }
    return Document(page_content=text, metadata=base | metadata)


def test_metadata_survives_splitting():
    unit = _unit(" ".join(f"Sentence number {n} about returns." for n in range(60)))

    chunks = split_into_chunks([unit], chunk_size=200, chunk_overlap=30)

    assert len(chunks) > 1
    for chunk in chunks:
        assert set(chunk.metadata) >= CONTRACT_KEYS
        assert chunk.metadata["section"] == "2.1 Opened items"


def test_chunk_ids_are_readable_unique_and_numbered_per_source():
    units = [_unit("a " * 300), _unit("b " * 300, source="other.md")]

    chunks = split_into_chunks(units, chunk_size=200, chunk_overlap=0)

    ids = [chunk.metadata["chunk_id"] for chunk in chunks]
    assert len(ids) == len(set(ids))
    assert ids[0] == "policy.md::0000"
    assert any(chunk_id == "other.md::0000" for chunk_id in ids)


def test_neighbouring_chunks_share_the_overlap():
    unit = _unit(" ".join(f"word{n}" for n in range(200)))

    first, second = split_into_chunks([unit], chunk_size=300, chunk_overlap=60)[:2]

    shared = first.page_content[-40:].split()[-1]
    assert shared in second.page_content


def test_short_units_are_not_split():
    chunks = split_into_chunks(
        [_unit("Return within 14 days.")], chunk_size=1500, chunk_overlap=225
    )

    assert [chunk.page_content for chunk in chunks] == ["Return within 14 days."]


def test_context_header_names_document_and_section_path():
    chunk = add_context_headers([_unit("Opened items: 10 percent fee.")])[0]

    assert chunk.page_content.splitlines()[0] == ("Refund Policy > 2. Condition > 2.1 Opened items")
    assert chunk.metadata["context_header"] == chunk.page_content.splitlines()[0]


def test_context_header_for_a_price_row_uses_the_sku():
    metadata = {"doc_title": "Pricing Guide", "sku": "F5-PF1"}

    assert context_header(metadata) == "Pricing Guide > F5-PF1"


def test_over_long_chunks_are_refused():
    chunk = _unit("token " * 9000, chunk_id="policy.md::0000")

    with pytest.raises(ChunkTooLongError, match=r"policy\.md::0000"):
        assert_within_embedding_limit([chunk], "text-embedding-3-small")


def test_statistics_report_counts_and_lengths():
    chunks = [_unit("abc"), _unit("abcdefg")]

    statistics = chunk_statistics(chunks, "text-embedding-3-small")

    assert (statistics.count, statistics.max_characters, statistics.mean_characters) == (2, 7, 5)


def test_production_chunks_of_the_real_knowledge_base_keep_their_metadata():
    settings = get_settings()
    units = load_knowledge_base(settings.knowledge_base_dir).documents

    chunks = build_chunks(units, settings)

    assert len({chunk.metadata["chunk_id"] for chunk in chunks}) == len(chunks)
    for chunk in chunks:
        assert set(chunk.metadata) >= CONTRACT_KEYS | {"chunk_id", "context_header"}
        assert chunk.metadata.get("section") or chunk.metadata.get("sku")
    price_rows = [chunk for chunk in chunks if chunk.metadata["source"] == "pricing_guide.csv"]
    assert len(price_rows) == len({chunk.metadata["sku"] for chunk in price_rows})


def test_headers_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("CHUNK_CONTEXT_HEADERS", "false")
    settings = load_settings(env_file=None)

    chunks = build_chunks([_unit("Short text.")], settings)

    assert chunks[0].page_content == "Short text."
    assert "context_header" not in chunks[0].metadata
