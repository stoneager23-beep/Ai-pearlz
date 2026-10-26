"""Whitespace normalisation, running-line detection and section splitting."""

from src.ingestion.text_cleaning import (
    Section,
    collapse_whitespace,
    find_repeated_lines,
    has_body_text,
    remove_lines,
    split_numbered_sections,
    split_plain_text_sections,
    strip_markdown_heading_marks,
)


def test_collapse_whitespace_keeps_line_structure():
    text = "  Line   one\t\twith  gaps  \n\n\n\nLine two\x7f\n"

    assert collapse_whitespace(text) == "Line one with gaps\n\nLine two"


WORDS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]


def _body(word: str) -> list[str]:
    # The middle lines repeat on every page, as a recurring table heading or step would.
    return [
        f"{word} opening",
        "Step 1 of the procedure",
        "1",
        "Shared table heading",
        f"{word} body",
        f"{word} closing",
    ]


def _page(number: int, word: str) -> str:
    return "\n".join(["Acme Manual | Rev A", f"Page {number}", *_body(word), "acme.example"])


PAGES = [_page(number, word) for number, word in enumerate(WORDS, start=1)]


def test_running_lines_are_found_with_page_numbers_ignored():
    assert find_repeated_lines(PAGES) == {"Acme Manual | Rev A", "Page #", "acme.example"}


def test_recurring_body_lines_are_kept():
    cleaned = remove_lines(PAGES[0], find_repeated_lines(PAGES))

    assert cleaned.splitlines() == _body("Alpha")


def test_bare_numbers_at_the_page_edge_are_not_running_lines():
    pages = [f"7\n{word} text\nmore {word}\nend {word}" for word in WORDS]

    assert find_repeated_lines(pages) == set()


def test_running_line_detection_needs_enough_pages():
    assert find_repeated_lines(["Header text\nA", "Header text\nB"]) == set()


def test_a_line_on_a_minority_of_pages_is_kept():
    pages = ["Header text\nWarning", "Header text\nWarning"]
    pages += [f"Header text\n{word}" for word in WORDS[:3]]

    assert find_repeated_lines(pages) == {"Header text"}
    assert remove_lines(pages[0], {"Header text"}) == "Warning"


def test_numbered_sections_carry_the_previous_heading_across_pages():
    text = "continued from the last page\n4. Specifications\nFlow 1.8 L/min\n4.1 Performance\nGood"

    assert split_numbered_sections(text, carried_heading="3. Box contents") == [
        Section("3. Box contents", "continued from the last page"),
        Section("4. Specifications", "4. Specifications\nFlow 1.8 L/min"),
        Section("4.1 Performance", "4.1 Performance\nGood"),
    ]


def test_table_cells_and_wrapped_lines_are_not_headings():
    text = (
        "2. Safety\nPlug into a socket rated 220-240 V,\n50 Hz. Do not use adaptors.\n48 W; standby"
    )

    assert [section.heading for section in split_numbered_sections(text, "")] == ["2. Safety"]


def test_plain_text_sections_split_at_capitalised_lines():
    text = (
        "RELEASE NOTES\nIntro\n\nVERSION 2.4.0 - released 12 May 2026\n- E-06 changed\nFixes\n- one"
    )

    sections = split_plain_text_sections(text)

    assert [section.heading for section in sections] == [
        "RELEASE NOTES",
        "VERSION 2.4.0 - released 12 May 2026",
    ]
    assert "Fixes" in sections[1].text


def test_markdown_heading_marks_are_removed_but_text_kept():
    assert strip_markdown_heading_marks("### 3.2 Exclusions\nText #1") == "3.2 Exclusions\nText #1"


def test_heading_only_text_has_no_body():
    assert not has_body_text("2. Empty heading", "2. Empty heading")
    assert has_body_text("1. Window\nReturn within 14 days.", "1. Window")
