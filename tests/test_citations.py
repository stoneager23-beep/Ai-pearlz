"""Citation validation, de-duplication and renumbering (Task 10)."""

from src.chains.citations import resolve_citations
from src.chains.schemas import AnswerDraft, Confidence
from tests.chain_fixtures import scored_chunk


def _draft(answer: str, sources: list[str]) -> AnswerDraft:
    return AnswerDraft(answer=answer, sources=sources, confidence=Confidence.HIGH, answered=True)


SUPPLIED = {
    "S1": scored_chunk("w::0", "Periods text.", 0.7),
    "S2": scored_chunk("w::1", "More periods text.", 0.6),
    "S3": scored_chunk("r::0", "Return text.", 0.5, source="refund.md", section="1. Window"),
}


def test_label_not_supplied_is_dropped_and_reported():
    resolved = resolve_citations(_draft("A [S1]. B [S5].", ["S1", "S5"]), SUPPLIED)

    assert resolved.invalid_labels == ["S5"]
    assert resolved.answer == "A [1]. B."
    assert [c.labels for c in resolved.citations] == [["S1"]]


def test_chunks_from_the_same_location_become_one_citation():
    resolved = resolve_citations(_draft("A [S1]. B [S2]. C [S3].", ["S1", "S2", "S3"]), SUPPLIED)

    assert [(c.number, c.source, c.labels) for c in resolved.citations] == [
        (1, "warranty_policy.md", ["S1", "S2"]),
        (2, "refund.md", ["S3"]),
    ]
    assert resolved.answer == "A [1]. B [1]. C [2]."


def test_numbering_follows_first_use_in_the_answer():
    resolved = resolve_citations(_draft("First [S3], then [S1].", ["S1", "S3"]), SUPPLIED)

    assert [c.source for c in resolved.citations] == ["refund.md", "warranty_policy.md"]
    assert resolved.answer == "First [1], then [2]."


def test_grouped_labels_are_rewritten():
    resolved = resolve_citations(_draft("Both [S1, S3].", ["S1", "S3"]), SUPPLIED)

    assert resolved.answer == "Both [1][2]."


def test_sources_listed_but_not_used_inline_still_count():
    resolved = resolve_citations(_draft("No inline markers.", ["S3"]), SUPPLIED)

    assert [c.source for c in resolved.citations] == ["refund.md"]


def test_no_citations_at_all():
    resolved = resolve_citations(_draft("Nothing cited.", []), SUPPLIED)

    assert resolved.citations == []
    assert resolved.invalid_labels == []


def test_snippet_is_verbatim_without_the_context_header():
    resolved = resolve_citations(_draft("A [S1].", ["S1"]), SUPPLIED)

    assert resolved.citations[0].snippet == "Periods text."


def test_snippet_is_the_passage_that_supports_the_citing_sentence():
    table = (
        "| E-01 | Single long tone | Water supply interrupted | Open the feed-water valve. |\n"
        "| E-03 | Triple short tone; FILTER indicator pulses red | Sediment pre-filter (PF-1) "
        "saturation | Replace PF-1, then hold RESET for 5 seconds. |\n"
        "| E-08 | Short tone every 2 seconds | Display not communicating | Unplug for 1 minute. |"
    )
    supplied = {"S1": scored_chunk("t::0", table, 0.6, section="3. Audible Alert Codes")}
    answer = "That is alert E-03: replace the PF-1 pre-filter and hold RESET for 5 seconds [S1]."

    resolved = resolve_citations(_draft(answer, ["S1"]), supplied)

    assert resolved.citations[0].snippet.startswith("| E-03 | Triple short tone")


def test_citation_at_paragraph_end_supports_the_sentences_before_it():
    table = (
        "| Code | Pattern | Meaning |\n|---|---|---|\n"
        "| E-01 | Single long tone | No water reaching the purifier; the purifier restarts. |\n"
        "| E-03 | Triple short tone | Pre-filter PF-1 saturation; replace PF-1, hold RESET. |"
    )
    supplied = {"S1": scored_chunk("t::0", table, 0.6, section="3. Audible Alert Codes")}
    answer = (
        "This is alert E-03: the sediment pre-filter PF-1 is saturated. Replace PF-1 and hold "
        "RESET. This will stop the purifier alert [S1]."
    )

    resolved = resolve_citations(_draft(answer, ["S1"]), supplied)

    assert resolved.citations[0].snippet.startswith("| E-03 |")


def test_snippet_is_a_contiguous_quote_even_around_a_table_separator():
    table = (
        "2. Warranty periods\n| Product | Warranty period |\n|---|---|\n"
        "| AquaPearl 500 Pro | 24 months for the purifier body, pump and electronics |"
    )
    supplied = {"S1": scored_chunk("w::0", table, 0.7)}

    resolved = resolve_citations(
        _draft("The AquaPearl 500 Pro has 24 months [S1].", ["S1"]), supplied
    )

    snippet = resolved.citations[0].snippet
    assert "|---|" not in snippet
    assert snippet in " ".join(table.split())
