"""Shared retrieval-only measurement: does a retrieved chunk actually contain the answer?

Used by the chunking (Task 03) and retriever (Task 06) experiments. No LLM is involved, so the
numbers measure retrieval alone (viva Q11).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document

QUESTIONS_FILE = Path(__file__).resolve().parent / "retrieval_questions.json"


@dataclass(frozen=True)
class RetrievalQuestion:
    id: str
    question: str
    accepted_sources: tuple[str, ...]
    answer_patterns: tuple[str, ...]
    chunking_sample: bool


def load_retrieval_questions(path: Path = QUESTIONS_FILE) -> list[RetrievalQuestion]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        RetrievalQuestion(
            id=item["id"],
            question=item["question"],
            accepted_sources=tuple(item["accepted_sources"]),
            answer_patterns=tuple(item["answer_patterns"]),
            chunking_sample=item["chunking_sample"],
        )
        for item in raw["questions"]
    ]


def contains_answer(question: RetrievalQuestion, chunk: Document) -> bool:
    """True if the chunk comes from an accepted source and matches every answer pattern."""
    if chunk.metadata["source"] not in question.accepted_sources:
        return False
    return all(
        re.search(pattern, chunk.page_content, flags=re.IGNORECASE)
        for pattern in question.answer_patterns
    )


def first_hit_rank(question: RetrievalQuestion, ranked: list[Document]) -> int | None:
    """1-based rank of the first chunk that contains the answer, or None."""
    for rank, chunk in enumerate(ranked, start=1):
        if contains_answer(question, chunk):
            return rank
    return None
