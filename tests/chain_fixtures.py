"""Shared helpers for chain tests: scored chunks and drafts."""

from langchain_core.documents import Document

from src.chains.schemas import AnswerDraft, Confidence


def scored_chunk(
    chunk_id: str,
    text: str,
    score: float,
    *,
    source: str = "warranty_policy.md",
    section: str = "2. Warranty periods",
) -> Document:
    header = f"Warranty Policy > {section}"
    return Document(
        page_content=f"{header}\n{text}",
        metadata={
            "chunk_id": chunk_id,
            "source": source,
            "doc_title": "Warranty Policy",
            "doc_type": "policy",
            "product_lines": ["all"],
            "version": "3.1",
            "last_updated": "2026-04-01",
            "section": section,
            "context_header": header,
            "score": score,
        },
    )


def draft(
    answer: str,
    sources: list[str],
    confidence: Confidence = Confidence.HIGH,
    *,
    answered: bool = True,
) -> AnswerDraft:
    return AnswerDraft(answer=answer, sources=sources, confidence=confidence, answered=answered)
