"""Page sections built from the design system: answers, sources, confidence, the inspector.

Every piece of text that comes from a person, the model or a document is HTML-escaped before
it is placed in markup, so neither a question nor a planted line in a document can inject HTML.
The functions that return strings are pure (and unit-tested); `show` writes markup to the page.
"""

import html
import re

import streamlit as st

from app.state import ChatTurn
from app.ui.icons import icon
from src.chains.schemas import Citation, Confidence, RefusalReason, SupportResponse
from src.config import ChatModelOption
from src.retrieval.vector_store import IndexManifest, describe_manifest

MILLISECONDS = 1000
SCORE_DECIMALS = 3
_NUMBERED_MARKER = re.compile(r"\[(\d+)\]")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

CONFIDENCE_LABELS = {
    Confidence.HIGH: "Answered from our documents",
    Confidence.PARTIAL: "Partly answered",
    Confidence.NONE: "Not in our documents",
}
DOC_TYPE_LABELS = {
    "faq": "FAQ",
    "guide": "Guides",
    "manual": "Manuals",
    "policy": "Policies",
    "pricing": "Pricing",
    "release_notes": "Release notes",
}


def show(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def escape(text: str) -> str:
    return html.escape(text, quote=True)


def _markdown_safe(text: str) -> str:
    """Escape HTML, and the dollar sign, which Streamlit's markdown would read as maths."""
    return html.escape(text, quote=False).replace("$", r"\$")


def answer_markup(answer: str) -> str:
    """The answer as markdown with HTML-escaped text and styled [1] references."""
    return _NUMBERED_MARKER.sub(
        r'<span class="sp-ref" aria-label="source \1">\1</span>', _markdown_safe(answer)
    )


def streamable(piece: str) -> str:
    """A piece of streamed answer text, made safe to append to the markdown on the page."""
    return _markdown_safe(piece)


def user_bubble(question: str) -> str:
    return f'<div class="sp-user-text">{escape(question)}</div>'


def brand() -> str:
    return f'<div class="sp-brand">{icon("drop", 20)}<span>SupportPearlz</span></div>'


def hero(eyebrow: str, title: str, body: str) -> str:
    return (
        f'<div class="sp-hero"><div class="sp-eyebrow">{escape(eyebrow)}</div>'
        f"<h1>{escape(title)}</h1><p>{escape(body)}</p></div>"
    )


def note(icon_name: str, text: str) -> str:
    return f'<div class="sp-note">{icon(icon_name, 14)}<span>{text}</span></div>'


def message(kind: str, text: str) -> str:
    """A short status message: kind is "error" or "ok"."""
    symbol = "info" if kind == "error" else "shield"
    return (
        f'<div class="sp-message sp-message--{kind}" role="status">'
        f"{icon(symbol)}<span>{escape(text)}</span></div>"
    )


def side_label(text: str) -> str:
    return f'<div class="sp-side-label">{escape(text)}</div>'


def confidence_chip(confidence: Confidence) -> str:
    return (
        f'<span class="sp-chip sp-chip--{confidence}"><i aria-hidden="true"></i>'
        f"{escape(CONFIDENCE_LABELS[confidence])}</span>"
    )


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / MILLISECONDS:.1f} s"


def meta_row(turn: ChatTurn) -> str:
    response = turn.response
    parts = [
        response.model,
        f"{response.usage.total_tokens:,} tokens",
        _seconds(response.latency_ms),
    ]
    return (
        f'<div class="sp-meta-row">{confidence_chip(response.confidence)}'
        f'<span class="sp-muted">{escape(" · ".join(parts))}</span></div>'
    )


def source_cards(citations: list[Citation]) -> str:
    cards = []
    for position, citation in enumerate(citations):
        cards.append(
            f'<details class="sp-source" style="--i:{position}">'
            "<summary>"
            f'<span class="sp-source-head"><span class="sp-source-num">{citation.number}</span>'
            f"{icon('document', 14)}<span>{escape(citation.doc_title)}</span></span>"
            f'<span class="sp-source-loc">{escape(citation.location)} · {escape(citation.source)}'
            "</span></summary>"
            f"<blockquote>{escape(citation.snippet)}</blockquote>"
            "</details>"
        )
    return f'<div class="sp-sources" aria-label="Sources">{"".join(cards)}</div>'


def refusal_card(response: SupportResponse, support_contact: str) -> str:
    """A refusal, framed as a helpful next step rather than an error."""
    title = (
        "Not covered by our documents"
        if response.refusal_reason is RefusalReason.GATE
        else "Not enough in our documents to answer"
    )
    email = _EMAIL.search(support_contact)
    action = (
        f'<a class="sp-action" href="mailto:{escape(email.group())}">{icon("mail")}'
        "Email Pearlz support</a>"
        if email
        else ""
    )
    return (
        f'<div class="sp-refusal"><div class="sp-refusal-title">{icon("info", 14)}{title}</div>'
        f'<div class="sp-answer">{escape(response.answer)}</div>{action}</div>'
    )


def error_card(response: SupportResponse) -> str:
    return message("error", response.error_message or response.answer)


def thinking_skeleton() -> str:
    return (
        '<div class="sp-skeleton" role="status" aria-label="Searching the documents">'
        "<span></span><span></span><span></span></div>"
    )


def _row(term: str, value: str) -> str:
    return f"<dt>{escape(term)}</dt><dd>{value}</dd>"


def _hits(response: SupportResponse) -> str:
    cited = {chunk_id for citation in response.sources for chunk_id in citation.chunk_ids}
    rows = []
    for chunk in response.retrieved:
        width = max(0.0, min(chunk.score, 1.0)) * 100
        state = "cited" if chunk.chunk_id in cited else "not cited"
        rows.append(
            '<div class="sp-hit">'
            f"<b>{escape(chunk.label or '-')}</b><span>{chunk.score:.{SCORE_DECIMALS}f}</span>"
            f'<span><span class="sp-bar"><span style="width:{width:.0f}%"></span></span>'
            f"{escape(chunk.source)} · {escape(chunk.location)} ({state})</span></div>"
        )
    return f'<div class="sp-hits">{"".join(rows)}</div>' if rows else "No chunks retrieved."


def inspector(turn: ChatTurn) -> str:
    """The "Behind the answer" panel. It shows no key and nothing derived from one."""
    response = turn.response
    rewritten = response.standalone_question != response.original_question
    searched = escape(response.standalone_question) + (
        ' <span class="sp-muted">(rewritten from the conversation)</span>' if rewritten else ""
    )
    if response.gate is None:
        gate = "not reached"
    else:
        best = "no match" if response.gate.best_score is None else f"{response.gate.best_score:.3f}"
        verdict = "passed" if response.gate.passed else "stopped the question"
        gate = escape(f"{verdict}: best match {best}, threshold {response.gate.threshold:.2f}")
    timing = f"complete after {_seconds(response.latency_ms)}"
    if turn.first_words_ms is not None:
        timing = f"first words after {_seconds(turn.first_words_ms)}, {timing}"
    checks = [
        "context trimmed to fit" if response.context_truncated else "all retrieved text fit",
        "unknown citations removed: " + ", ".join(response.invalid_citations)
        if response.invalid_citations
        else "every citation points at a retrieved chunk",
    ]
    rows = [
        _row("Your question", escape(response.original_question)),
        _row("Searched for", searched),
        _row("Relevance gate", gate),
        _row("Model", escape(f"{response.model}, prompt {response.prompt_version}")),
        _row(
            "Tokens",
            escape(f"{response.usage.input_tokens:,} in, {response.usage.output_tokens:,} out"),
        ),
        _row("Time", escape(timing)),
        _row("Checks", escape("; ".join(checks))),
    ]
    return (
        f'<div class="sp-inspect"><dl>{"".join(rows)}</dl>'
        f'<div class="sp-side-label">Retrieved chunks (cosine similarity)</div>{_hits(response)}'
        "</div>"
    )


def kb_stats(manifest: IndexManifest) -> str:
    rows = "".join(
        f'<div class="sp-kv-row"><span>{escape(name)}</span><span>{escape(value)}</span></div>'
        for name, value in describe_manifest(manifest).items()
    )
    return f'<div class="sp-kv">{rows}</div>'


def how_it_works(threshold: float, k: int) -> str:
    steps = [
        "A follow-up question is first rewritten so it makes sense on its own.",
        f"The question is matched against the knowledge base; the {k} closest passages are kept.",
        f"If even the best match scores below {threshold:.2f}, the assistant declines "
        "instead of guessing, and points you to a person.",
        "Otherwise the model answers only from those passages and cites each one.",
        "Citations are checked against what was retrieved before the answer is shown.",
    ]
    return '<ol class="sp-steps">' + "".join(f"<li>{escape(s)}</li>" for s in steps) + "</ol>"


def retirement_note(option: ChatModelOption) -> str:
    if option.retires_on is None:
        return ""
    return f"Retires from the OpenAI API on {option.retires_on:%d %b %Y}."


def product_chips(lines: list[str]) -> str:
    chips = "".join(f'<span class="sp-line-chip">{escape(line)}</span>' for line in lines)
    return f'<div class="sp-chips">{chips}</div>'
