"""Text normalisation and section detection for loaded documents.

Cleaning is deliberately conservative: it collapses whitespace and removes running page
headers and footers, but keeps line breaks, headings and table rows, because the chunker and
the citation step rely on that structure.
"""

import re
from collections import Counter
from dataclasses import dataclass

# A line that repeats on at least this share of a PDF's pages is a running header or footer.
REPEATED_LINE_PAGE_SHARE = 0.6
# Below this many pages, "repeated on most pages" is not meaningful evidence of a header.
MIN_PAGES_FOR_HEADER_DETECTION = 3
# Headers and footers are looked for only among a page's first and last few lines, so a body
# line that happens to recur (a table heading, "Step 1") is never stripped.
EDGE_LINES_PER_PAGE = 3
# A running line must contain words; bare list numbers such as "1" are structure, not footers.
MIN_LETTERS_IN_RUNNING_LINE = 3

_HORIZONTAL_SPACE = re.compile(r"[ \t\xa0]+")
# Control characters except newline and tab; pypdf can emit them, e.g. for list bullets.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_THREE_OR_MORE_NEWLINES = re.compile(r"\n{3,}")
_DIGITS = re.compile(r"\d+")
_MARKDOWN_EMPHASIS = re.compile(r"\*\*(.+?)\*\*")
_MARKDOWN_HEADING_MARKS = re.compile(r"^#{1,6}\s+", flags=re.MULTILINE)
# "13. Audible alert codes" or "11.2 Replacing the PF-1 sediment pre-filter". The number must
# contain a dot, which rules out wrapped body lines and table cells such as "48 W; standby".
_NUMBERED_HEADING = re.compile(r"^(\d{1,2}\.|\d{1,2}\.\d{1,2}\.?)\s+[A-Z][^\n]{2,80}$")
# Plain-text section heading: a line that starts with an all-capitals word of 4+ letters.
_PLAIN_TEXT_HEADING = re.compile(r"^[A-Z]{4,}\b[^\n]*$")


@dataclass(frozen=True)
class Section:
    """A heading and the text that follows it, up to the next heading."""

    heading: str
    text: str


def collapse_whitespace(text: str) -> str:
    """Remove control characters, collapse spaces and tabs, trim lines, allow one blank line."""
    text = _CONTROL_CHARACTERS.sub("", text)
    lines = [_HORIZONTAL_SPACE.sub(" ", line).strip() for line in text.splitlines()]
    return _THREE_OR_MORE_NEWLINES.sub("\n\n", "\n".join(lines)).strip()


def strip_markdown_emphasis(text: str) -> str:
    """Turn **bold** into bold. Headings and table pipes are kept as structure."""
    return _MARKDOWN_EMPHASIS.sub(r"\1", text)


def strip_markdown_heading_marks(text: str) -> str:
    """Turn "### 3.2 Exclusions" into "3.2 Exclusions"; the heading text itself is kept."""
    return _MARKDOWN_HEADING_MARKS.sub("", text)


def _line_signature(line: str) -> str:
    # "Page 7" and "Page 8" are the same footer, so digits are ignored when comparing lines.
    return _DIGITS.sub("#", line.strip())


def _is_edge(index: int, line_count: int) -> bool:
    return index < EDGE_LINES_PER_PAGE or index >= line_count - EDGE_LINES_PER_PAGE


def _edge_lines(page: str) -> list[str]:
    lines = [line for line in page.splitlines() if line.strip()]
    return [line for index, line in enumerate(lines) if _is_edge(index, len(lines))]


def find_repeated_lines(pages: list[str]) -> set[str]:
    """Signatures of running headers and footers: edge lines that recur on most pages."""
    if len(pages) < MIN_PAGES_FOR_HEADER_DETECTION:
        return set()
    pages_containing: Counter[str] = Counter()
    for page in pages:
        pages_containing.update(
            {
                _line_signature(line)
                for line in _edge_lines(page)
                if sum(character.isalpha() for character in line) >= MIN_LETTERS_IN_RUNNING_LINE
            }
        )
    minimum_pages = REPEATED_LINE_PAGE_SHARE * len(pages)
    return {signature for signature, count in pages_containing.items() if count >= minimum_pages}


def remove_lines(text: str, signatures: set[str]) -> str:
    """Drop edge lines whose signature is in `signatures`; body lines are never touched."""
    lines = [line for line in text.splitlines() if line.strip()]
    kept = [
        line
        for index, line in enumerate(lines)
        if not (_is_edge(index, len(lines)) and _line_signature(line) in signatures)
    ]
    return "\n".join(kept)


def split_numbered_sections(text: str, carried_heading: str) -> list[Section]:
    """Split PDF page text at numbered headings ("4. Technical specifications").

    Text before the first heading on a page continues the section from the previous page,
    so it is labelled with `carried_heading`.
    """
    return _split_at_headings(text, _NUMBERED_HEADING, carried_heading)


def split_plain_text_sections(text: str) -> list[Section]:
    """Split plain text at lines that start with an all-capitals word ("VERSION 2.4.0 ...")."""
    return _split_at_headings(text, _PLAIN_TEXT_HEADING, carried_heading="")


def _split_at_headings(text: str, heading: re.Pattern[str], carried_heading: str) -> list[Section]:
    sections: list[Section] = []
    current_heading = carried_heading
    current_lines: list[str] = []
    for line in text.splitlines():
        if heading.match(line.strip()):
            if any(existing.strip() for existing in current_lines):
                sections.append(Section(current_heading, "\n".join(current_lines).strip()))
            current_heading = line.strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if any(existing.strip() for existing in current_lines):
        sections.append(Section(current_heading, "\n".join(current_lines).strip()))
    return sections


def has_body_text(text: str, heading: str) -> bool:
    """True if `text` contains something besides its own heading line."""
    body = text.replace(heading, "", 1) if heading else text
    return bool(body.strip(" #\n"))
