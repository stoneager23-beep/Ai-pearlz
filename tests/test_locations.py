"""Location labels point to the most specific place a person can check."""

from src.retrieval.locations import location_label


def test_pdf_location_has_page_and_section():
    metadata = {"page_number": 16, "section": "13. Audible alert codes", "doc_title": "Manual"}

    assert location_label(metadata) == "p. 16, 13. Audible alert codes"


def test_pdf_cover_page_shows_only_the_page():
    metadata = {"page_number": 1, "section": "Manual", "doc_title": "Manual"}

    assert location_label(metadata) == "p. 1"


def test_numbered_section_gets_a_section_sign():
    assert (
        location_label({"section": "3.2 Exclusions", "doc_title": "Warranty"}) == "§3.2 Exclusions"
    )


def test_unnumbered_section_is_quoted():
    metadata = {"section": "How long is my warranty?", "doc_title": "FAQ"}

    assert location_label(metadata) == '"How long is my warranty?"'


def test_price_row_shows_the_sku():
    assert location_label({"sku": "F5-PF1", "row": 5, "doc_title": "Pricing"}) == "SKU F5-PF1"
