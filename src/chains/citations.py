"""Validate the model's citations and resolve them to documents and locations (Task 10).

The model cites context blocks by label ([S2]) inline in its answer and lists them in
`sources`. This module:

1. collects every label the model claimed, inline first, then any extra ones in `sources`;
2. drops labels that were never supplied (a fabricated [S5] when only four blocks were given)
   and records them, because a fake citation is worse than none;
3. de-duplicates: several chunks from the same document location become one citation;
4. numbers citations [1], [2] in order of first use and rewrites the inline markers to match;
5. attaches a short verbatim snippet, so a person can check the claim without opening the file.

Only labels the model actually cited are shown: listing every retrieved chunk is not
attribution (manual mistake #9).
"""

import re
import textwrap
from dataclasses import dataclass

from langchain_core.documents import Document

from src.chains.context import chunk_body
from src.chains.schemas import AnswerDraft, Citation
from src.retrieval.locations import location_label

SNIPPET_CHARACTERS = 220
# Shorter pieces (such as PDF table cells, extracted one per line) are joined to the next.
MIN_PASSAGE_CHARACTERS = 80
# "[S1]", "[S1, S3]" or "[S1][S2]"; the label group is split on commas.
_INLINE_CITATION = re.compile(r"\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:])")
_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Words too common to say anything about which passage supports an answer.
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have if in is it its no not of on or "  # noqa: SIM905
    "that the this to will with you your".split()
)


@dataclass(frozen=True)
class ResolvedAnswer:
    answer: str
    citations: list[Citation]
    invalid_labels: list[str]


def _labels_in_order(draft: AnswerDraft) -> list[str]:
    labels: list[str] = []
    for match in _INLINE_CITATION.finditer(draft.answer):
        labels += [label.strip() for label in match.group(1).split(",")]
    labels += draft.sources
    return list(dict.fromkeys(label.strip() for label in labels))


def _content_words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower())) - _STOPWORDS


def _labels_in(sentence: str) -> set[str]:
    return {
        part.strip()
        for match in _INLINE_CITATION.finditer(sentence)
        for part in match.group(1).split(",")
    }


def _sentences_citing(answer: str, label: str) -> str:
    """The part of the answer that `label` supports, or the whole answer if it is not inline.

    A citation at the end of a sentence supports that sentence and the uncited sentences just
    before it, since models often cite once at the end of a paragraph.
    """
    supported: list[str] = []
    pending: list[str] = []
    for sentence in _SENTENCE_END.split(answer):
        labels = _labels_in(sentence)
        if not labels:
            pending.append(sentence)
            continue
        if label in labels:
            supported += [*pending, sentence]
        pending = []
    return " ".join(supported) or answer


def _is_table_row(line: str) -> bool:
    return " | " in line or line.lstrip().startswith("|")


def _is_table_separator(line: str) -> bool:
    """The |---|---| line under a Markdown table header: structure, never evidence."""
    return bool(line.strip()) and set(line.strip()) <= set("|-: ")


def _passages(text: str) -> list[str]:
    """Candidate snippets: table rows kept whole, prose joined across line wraps and split into
    sentences, and very short pieces (PDF table cells) merged with the next."""
    pieces: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            pieces.extend(_SENTENCE_END.split(" ".join(paragraph)))
            paragraph.clear()

    for line in text.splitlines():
        if _is_table_separator(line):
            continue
        if _is_table_row(line):
            flush_paragraph()
            pieces.append(line.strip())
        elif line.strip():
            paragraph.append(line.strip())
        else:
            flush_paragraph()
    flush_paragraph()

    passages: list[str] = []
    buffer = ""
    for piece in pieces:
        buffer = f"{buffer} {piece}".strip()
        if len(buffer) >= MIN_PASSAGE_CHARACTERS:
            passages.append(buffer)
            buffer = ""
    if buffer:
        passages.append(buffer)
    return passages


def _snippet(chunk: Document, claim: str) -> str:
    """The verbatim passage of the chunk that best matches `claim`.

    Scoring is plain word overlap, scaled down for long passages so a whole table does not win
    just by being long. The snippet only helps a person find the supporting text quickly; it
    does not decide anything.
    """
    passages = _passages(chunk_body(chunk))
    claim_words = _content_words(claim)

    def overlap(passage: str) -> float:
        words = _content_words(passage)
        return len(words & claim_words) / (len(words) ** 0.5 + 1)

    best = max(passages, key=overlap, default="")
    return textwrap.shorten(" ".join(best.split()), SNIPPET_CHARACTERS, placeholder="...")


def resolve_citations(draft: AnswerDraft, supplied: dict[str, Document]) -> ResolvedAnswer:
    """Keep only supplied labels, merge those pointing at the same place, and renumber."""
    claimed = _labels_in_order(draft)
    invalid = [label for label in claimed if label not in supplied]

    citations: list[Citation] = []
    number_of_label: dict[str, int] = {}
    citation_at: dict[tuple[str, str], Citation] = {}
    for label in (label for label in claimed if label in supplied):
        chunk = supplied[label]
        key = (chunk.metadata["source"], location_label(chunk.metadata))
        citation = citation_at.get(key)
        if citation is None:
            citation = Citation(
                number=len(citations) + 1,
                source=chunk.metadata["source"],
                doc_title=chunk.metadata["doc_title"],
                location=key[1],
                snippet=_snippet(chunk, _sentences_citing(draft.answer, label)),
                labels=[],
                chunk_ids=[],
            )
            citations.append(citation)
            citation_at[key] = citation
        citation.labels.append(label)
        citation.chunk_ids.append(chunk.metadata["chunk_id"])
        number_of_label[label] = citation.number

    def renumber(match: re.Match[str]) -> str:
        labels = [label.strip() for label in match.group(1).split(",")]
        numbers = sorted({number_of_label[label] for label in labels if label in number_of_label})
        return "".join(f"[{number}]" for number in numbers)

    answer = _INLINE_CITATION.sub(renumber, draft.answer)
    answer = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", answer).strip()
    return ResolvedAnswer(answer=answer, citations=citations, invalid_labels=invalid)
