"""Loader dispatch, the metadata contract, and per-file error handling (Task 02)."""

import json
import logging

import pytest

from src.config import get_settings
from src.ingestion.loaders import (
    FileStatus,
    IngestionError,
    describe_price_row,
    load_knowledge_base,
)
from tests.kb_builders import build_mixed_knowledge_base, encrypt_pdf, write_catalog

CONTRACT_KEYS = {"source", "doc_type", "product_lines", "version", "last_updated", "doc_title"}


@pytest.fixture
def kb_dir(tmp_path):
    folder = tmp_path / "kb"
    build_mixed_knowledge_base(folder)
    return folder


def _documents_from(result, source):
    return [doc for doc in result.documents if doc.metadata["source"] == source]


def _report_for(result, name):
    return next(report for report in result.reports if report.file_name == name)


def test_every_format_is_dispatched_and_loaded(kb_dir):
    result = load_knowledge_base(kb_dir)

    assert result.skipped_count == 0
    assert {report.file_type for report in result.reports} == {"pdf", "docx", "md", "txt", "csv"}


def test_every_document_carries_the_metadata_contract(kb_dir):
    result = load_knowledge_base(kb_dir)

    for document in result.documents:
        assert set(document.metadata) >= CONTRACT_KEYS
        assert document.metadata["source"]
        assert document.metadata["doc_type"]


def test_pdf_keeps_loader_page_metadata_and_adds_sections(kb_dir):
    pages = _documents_from(load_knowledge_base(kb_dir), "manual.pdf")

    assert [doc.metadata["page"] for doc in pages] == [0, 1, 1, 2]
    assert [doc.metadata["page_number"] for doc in pages] == [1, 2, 2, 3]
    assert [doc.metadata["section"] for doc in pages] == [
        "Title of manual.pdf",
        "1. Safety",
        "2. Cleaning",
        "2. Cleaning",
    ]


def test_pdf_running_header_and_footer_are_stripped(kb_dir):
    result = load_knowledge_base(kb_dir)

    for document in _documents_from(result, "manual.pdf"):
        assert "Acme Manual" not in document.page_content
        assert "Page " not in document.page_content
    assert set(_report_for(result, "manual.pdf").stripped_lines) == {
        "Acme Manual | Rev A",
        "Page #",
    }


def test_docx_is_split_at_headings(kb_dir):
    sections = _documents_from(load_knowledge_base(kb_dir), "agreement.docx")

    assert [doc.metadata["section"] for doc in sections] == ["1. Plans", "2. Claims"]
    assert sections[0].page_content == "1. Plans\nBasic plan costs PKR 6,500."


def test_markdown_sections_drop_heading_marks_and_empty_headings(kb_dir):
    sections = _documents_from(load_knowledge_base(kb_dir), "policy.md")

    assert [doc.metadata["section"] for doc in sections] == ["Policy", "1. Window", "2.1 Detail"]
    assert sections[1].page_content == "1. Window\nReturn within 14 days."
    assert sections[2].metadata["section_path"] == "2. Empty heading > 2.1 Detail"


def test_plain_text_is_split_at_capitalised_headings(kb_dir):
    sections = _documents_from(load_knowledge_base(kb_dir), "notes.txt")

    assert [doc.metadata["section"] for doc in sections] == [
        "RELEASE NOTES",
        "VERSION 2.0 - released 2026",
    ]


def test_csv_rows_become_self_describing_sentences(kb_dir):
    rows = _documents_from(load_knowledge_base(kb_dir), "prices.csv")

    assert [doc.metadata["sku"] for doc in rows] == ["F5-PF1", "AP250"]
    assert rows[0].metadata["product_lines"] == ["AquaPearl 500 Pro"]
    assert "Sediment pre-filter PF-1 (SKU F5-PF1)" in rows[0].page_content
    assert "List price: PKR 2,400." in rows[0].page_content
    assert "Current promotional price: PKR 1,990." in rows[0].page_content


def test_price_sentence_handles_missing_prices():
    sentence = describe_price_row(
        {
            "sku": "AP250",
            "product_name": "AquaPearl 250",
            "product_line": "AquaPearl 250",
            "category": "purifier",
            "description": "Old model",
            "list_price_pkr": "",
            "promo_price_pkr": "",
            "availability": "discontinued",
            "compatible_with": "",
            "notes": "",
        }
    )

    assert "no longer sold" in sentence
    assert "No promotional price is currently offered." in sentence


def test_corrupt_file_is_skipped_with_one_warning_and_the_rest_loads(kb_dir, caplog):
    (kb_dir / "broken.pdf").write_bytes(b"%PDF-1.4 this is not really a pdf")
    catalog = json.loads((kb_dir / "_catalog.json").read_text(encoding="utf-8"))
    catalog["broken.pdf"] = catalog["manual.pdf"]
    (kb_dir / "_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="src.ingestion.loaders"):
        result = load_knowledge_base(kb_dir)

    assert result.loaded_count == 5
    assert _report_for(result, "broken.pdf").status is FileStatus.SKIPPED
    warnings = [
        record.getMessage() for record in caplog.records if record.name == "src.ingestion.loaders"
    ]
    assert len(warnings) == 1
    assert "broken.pdf" in warnings[0]


def test_password_protected_pdf_is_skipped_with_that_reason(kb_dir):
    encrypt_pdf(kb_dir / "manual.pdf", kb_dir / "locked.pdf")
    catalog = json.loads((kb_dir / "_catalog.json").read_text(encoding="utf-8"))
    catalog["locked.pdf"] = catalog["manual.pdf"]
    (kb_dir / "_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    report = _report_for(load_knowledge_base(kb_dir), "locked.pdf")

    assert report.status is FileStatus.SKIPPED
    assert report.reason == "password-protected PDF"


def test_unsupported_and_uncatalogued_files_are_skipped(kb_dir):
    (kb_dir / "photo.png").write_bytes(b"\x89PNG")
    (kb_dir / "extra.md").write_text("# Extra\n\nText.\n", encoding="utf-8")

    result = load_knowledge_base(kb_dir)

    assert _report_for(result, "photo.png").reason == "unsupported file type .png"
    assert _report_for(result, "extra.md").reason == "no entry in _catalog.json"


def test_duplicate_content_is_skipped(kb_dir):
    (kb_dir / "policy_copy.md").write_text(
        (kb_dir / "policy.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    catalog = json.loads((kb_dir / "_catalog.json").read_text(encoding="utf-8"))
    catalog["policy_copy.md"] = catalog["policy.md"]
    (kb_dir / "_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    report = _report_for(load_knowledge_base(kb_dir), "policy_copy.md")

    assert report.reason == "duplicate of policy.md"


def test_underscore_files_are_never_loaded(kb_dir):
    (kb_dir / "_answer_key.md").write_text("# Gaps\n\nStudent discounts.\n", encoding="utf-8")

    result = load_knowledge_base(kb_dir)

    assert all(not report.file_name.startswith("_") for report in result.reports)


def test_files_in_subfolders_are_found(kb_dir):
    (kb_dir / "policies").mkdir()
    (kb_dir / "policies" / "extra.md").write_text("# Extra\n\nMore text.\n", encoding="utf-8")
    write_catalog(kb_dir, {"policies/extra.md": "policy"})

    result = load_knowledge_base(kb_dir)

    assert _report_for(result, "policies/extra.md").status is FileStatus.LOADED


def test_missing_catalogue_stops_ingestion(tmp_path):
    (tmp_path / "policy.md").write_text("# Policy\n\nText.\n", encoding="utf-8")

    with pytest.raises(IngestionError, match=r"_catalog.json not found"):
        load_knowledge_base(tmp_path)


def test_real_knowledge_base_loads_cleanly():
    result = load_knowledge_base(get_settings().knowledge_base_dir)

    assert result.skipped_count == 0
    assert result.loaded_count >= 10
    assert len({report.file_type for report in result.reports}) >= 3
    for document in result.documents:
        assert set(document.metadata) >= CONTRACT_KEYS
        assert document.metadata.get("section") or document.metadata.get("sku")
