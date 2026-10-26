"""Streaming the answer field out of the model's JSON tokens (bonus C4). No network."""

from uuid import uuid4

from src.chains.rag_chain import ANSWER_TAG
from src.chains.streaming import AnswerTextStream, displayable

TOKENS = [
    '{"ans',
    'wer": "The warranty',
    " is 24 months [S",
    "1]. Filters",
    ' are excluded [S2].", "sources": ["S1", "S2"], ',
    '"confidence": "high", "answered": true}',
]


def _drain(stream: AnswerTextStream) -> list[str]:
    pieces = []
    while not stream.pieces.empty():
        pieces.append(stream.pieces.get())
    return pieces


def _feed(stream: AnswerTextStream, tokens: list[str], tags: list[str]) -> None:
    run_id = uuid4()
    stream.on_chat_model_start({}, [[]], run_id=run_id, tags=tags)
    for token in tokens:
        stream.on_llm_new_token(token, run_id=run_id)


def test_answer_text_streams_without_raw_labels():
    stream = AnswerTextStream()

    _feed(stream, TOKENS, tags=[ANSWER_TAG])
    pieces = _drain(stream)

    assert "".join(pieces) == "The warranty is 24 months. Filters are excluded."
    assert not any("[" in piece for piece in pieces)
    assert len(pieces) > 1
    assert stream.first_piece_at is not None


def test_other_model_calls_are_ignored():
    stream = AnswerTextStream()

    _feed(stream, ["Is the PF-1 filter covered?"], tags=["condense"])

    assert stream.pieces.empty()


def test_a_label_still_arriving_is_held_back():
    assert displayable("Covered for 24 months [S") == "Covered for 24 months"
    assert (
        displayable("Covered for 24 months [S1, S2] and more") == "Covered for 24 months and more"
    )
