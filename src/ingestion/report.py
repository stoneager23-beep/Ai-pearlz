"""The ingestion report: what was found, loaded and skipped, per file (Task 02 evidence).

Usage:  python -m src.ingestion.report [--kb-dir PATH]

Prints the report and writes it to RESULTS_DIR/ingestion_report.md.
"""

import argparse
import sys
from pathlib import Path

from src.config import ConfigError, get_settings
from src.ingestion.loaders import FileStatus, IngestionError, IngestionResult, load_knowledge_base
from src.utils.logging_setup import configure_logging

REPORT_FILE_NAME = "ingestion_report.md"


def render_ingestion_report(result: IngestionResult, kb_dir: Path) -> str:
    """A Markdown report listing every file with its type, size, units and metadata keys."""
    lines = [
        "# Ingestion report",
        "",
        f"Knowledge base: `{kb_dir.name}`. "
        f"Files found: **{len(result.reports)}**, loaded: **{result.loaded_count}**, "
        f"skipped: **{result.skipped_count}**. Documents (structural units) produced: "
        f"**{len(result.documents)}**.",
        "",
        "| File | Type | Status | Characters | Pages | Units | Metadata keys | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for report in result.reports:
        if report.status is FileStatus.SKIPPED:
            notes = f"Skipped: {report.reason}"
        elif report.stripped_lines:
            notes = "Stripped running lines: " + "; ".join(
                f"`{line}`" for line in report.stripped_lines
            )
        else:
            notes = ""
        pages = str(report.pages) if report.pages else ""
        lines.append(
            f"| {report.file_name} | {report.file_type} | {report.status} | {report.characters:,} "
            f"| {pages} | {report.units} | {', '.join(report.metadata_keys)} | {notes} |"
        )
    lines += [
        "",
        "Units are the structural pieces each file is loaded as: page sections for PDF, heading "
        "sections for DOCX, Markdown and text, and rows for CSV. Running lines are page headers "
        "and footers found on at least 60% of a PDF's pages; digits are shown as `#`.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the knowledge base and report on it.")
    parser.add_argument("--kb-dir", type=Path, help="Folder to load (default: KNOWLEDGE_BASE_DIR)")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    configure_logging(settings)

    kb_dir = args.kb_dir or settings.knowledge_base_dir
    try:
        result = load_knowledge_base(kb_dir)
    except IngestionError as error:
        print(f"Ingestion failed: {error}", file=sys.stderr)
        return 1

    report = render_ingestion_report(result, kb_dir)
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    (settings.results_dir / REPORT_FILE_NAME).write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
