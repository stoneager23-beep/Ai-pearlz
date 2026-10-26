"""Human-readable location labels for chunks: the most specific place a person can check."""

from collections.abc import Mapping


def location_label(metadata: Mapping[str, object]) -> str:
    """The most specific location of a chunk.

    PDF: "p. 16, 13. Audible alert codes". Numbered section: "§3.2 Exclusions". Other section
    (an FAQ question): the heading in quotes. Price row: "SKU F5-PF1".
    """
    if metadata.get("sku"):
        return f"SKU {metadata['sku']}"
    section = str(metadata.get("section") or "")
    if section == metadata.get("doc_title"):
        section = ""
    if metadata.get("page_number"):
        page = f"p. {metadata['page_number']}"
        return f"{page}, {section}" if section else page
    if not section:
        return ""
    return f"§{section}" if section[0].isdigit() else f'"{section}"'
