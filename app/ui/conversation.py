"""The conversation: the empty state, past turns, and a new answer streaming in (bonus C4).

A new answer is produced in a worker thread while this script thread drains the answer text
from the callback queue into `st.write_stream`. The worker never touches Streamlit. Once the
answer is complete, the page reruns and shows it in full: references, confidence, sources and
the "Behind the answer" panel, all validated before display.
"""

import logging
import threading
import time
from queue import Empty

import streamlit as st

from app import state
from app.state import ChatTurn
from app.ui import components as ui
from app.ui.scene3d import HERO_HEIGHT, PearlState, pearl
from src.chains.schemas import RefusalReason, SupportResponse
from src.chains.session import SupportSession
from src.chains.streaming import AnswerTextStream
from src.config import Settings

POLL_SECONDS = 0.05
MILLISECONDS = 1000

# Each is a case in evaluation/test_questions.json, so the demo shows measured behaviour.
EXAMPLE_QUESTIONS = (
    "My purifier beeps three times and the light flashes red. What should I do?",  # T-05
    "How long is the warranty on the AquaPearl 500 Pro?",  # T-01
    "My AquaPearl 500 Pro shows E-06. What does it mean?",  # T-21
    "Do you offer student discounts?",  # T-12: not in the documents, so it is declined
)

logger = logging.getLogger(__name__)


def pearl_state_for(turns: list[ChatTurn], *, asking: bool) -> PearlState:
    if asking:
        return PearlState.THINKING
    if not turns:
        return PearlState.IDLE
    last = turns[-1].response
    return PearlState.REFUSED if last.refusal_reason is not None else PearlState.ANSWERED


def render_empty_state(product_lines: list[str]) -> None:
    """The ready screen (the pearl above it is drawn first, by the page)."""
    ui.show(
        '<div class="sp-empty"><div class="sp-eyebrow">Ready</div>'
        "<h2>How can we help with your AquaPearl?</h2>"
        "<p>Ask in your own words. Answers come only from Pearlz Home's documents, with "
        "sources, and the assistant says so when the documents do not cover something.</p>"
        "</div>"
    )
    columns = st.columns(2)
    for position, question in enumerate(EXAMPLE_QUESTIONS):
        columns[position % 2].button(
            question,
            key=f"sp-example-{position}",
            on_click=state.ask_later,
            args=(question,),
            width="stretch",
        )
    ui.show(product_lines and ui.product_chips(product_lines))


def _retry_last() -> None:
    turn = state.drop_last_turn()
    if turn is not None:
        state.ask_later(turn.question)


def _render_answer(turn: ChatTurn, settings: Settings) -> None:
    response = turn.response
    if response.refusal_reason is RefusalReason.ERROR:
        ui.show(ui.error_card(response))
        return
    if response.refusal_reason is not None:
        ui.show(ui.refusal_card(response, settings.support_contact))
    else:
        st.markdown(ui.answer_markup(response.answer), unsafe_allow_html=True)
    ui.show(ui.meta_row(turn))
    if response.sources:
        ui.show(ui.source_cards(response.sources))


def render_turns(turns: list[ChatTurn], settings: Settings) -> None:
    for position, turn in enumerate(turns):
        with st.container(key=f"sp-user-{position}"):
            ui.show(ui.user_bubble(turn.question))
        with st.container(key=f"sp-answer-{position}"):
            _render_answer(turn, settings)
            is_last = position == len(turns) - 1
            if is_last and turn.response.refusal_reason is RefusalReason.ERROR:
                st.button("Try again", key=f"sp-retry-{position}", on_click=_retry_last)
            with st.expander("Behind the answer"):
                ui.show(ui.inspector(turn))


def answer_new_question(question: str, session: SupportSession, position: int) -> None:
    """Stream the answer to `question`, keep the finished turn, and rerun to show it in full."""
    lock = state.ask_lock()
    stream = AnswerTextStream()
    outcome: dict[str, SupportResponse] = {}

    def work() -> None:
        with lock:
            outcome["response"] = session.ask(question, callbacks=[stream])

    started = time.perf_counter()
    worker = threading.Thread(target=work, name=f"answer-{session.session_id}", daemon=True)
    worker.start()

    with st.container(key=f"sp-user-{position}"):
        ui.show(ui.user_bubble(question))
    with st.container(key=f"sp-answer-{position}"):
        skeleton = st.empty()
        skeleton.markdown(ui.thinking_skeleton(), unsafe_allow_html=True)

        def pieces():  # noqa: ANN202 (a generator handed straight to st.write_stream)
            waiting = True
            while worker.is_alive() or not stream.pieces.empty():
                try:
                    piece = stream.pieces.get(timeout=POLL_SECONDS)
                except Empty:
                    continue
                if waiting:
                    skeleton.empty()
                    waiting = False
                yield ui.streamable(piece)

        st.write_stream(pieces())
    worker.join()

    response = outcome.get("response")
    if response is None:  # `ask` never raises, so this means the worker itself failed
        logger.error("Answer worker for session %s produced no response", session.session_id)
        ui.show(ui.message("error", "Something went wrong on our side. Please try again."))
        return
    first_words_ms = (
        None
        if stream.first_piece_at is None
        else round((stream.first_piece_at - started) * MILLISECONDS)
    )
    state.add_turn(ChatTurn(question, response, first_words_ms))
    st.rerun()


def render_hero_pearl() -> None:
    pearl(PearlState.IDLE, height=HERO_HEIGHT, key="pearl-hero")
