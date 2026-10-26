"""What one browser session keeps between reruns, in `st.session_state`.

`st.session_state` belongs to a single browser session: other visitors never see it, and it is
not written to disk. It is the only place the visitor's API key is kept, and so the only
place the objects built from the key live (the `SupportSession` with its chat model and query
embeddings). Nothing here is ever put in `st.cache_resource` or a module-level variable.
"""

import threading
from dataclasses import dataclass

import streamlit as st

from src.chains.schemas import SupportResponse
from src.chains.session import SupportSession

# Session-state keys. Widget keys are listed too, so "change or remove key" can clear them.
API_KEY = "sp_api_key"
AVAILABLE_MODELS = "sp_available_models"
SUPPORT_SESSION = "sp_support_session"
TURNS = "sp_turns"
PENDING_QUESTION = "sp_pending_question"
FLASH = "sp_flash"
INDEX_KEY = "sp_index_key"
ASK_LOCK = "sp_ask_lock"
MODEL_WIDGET = "sp_model"
DOC_TYPES_WIDGET = "sp_doc_types"
PRODUCT_WIDGET = "sp_product_line"

_SESSION_KEYS = (
    API_KEY,
    AVAILABLE_MODELS,
    SUPPORT_SESSION,
    TURNS,
    PENDING_QUESTION,
    INDEX_KEY,
    MODEL_WIDGET,
    DOC_TYPES_WIDGET,
    PRODUCT_WIDGET,
)


@dataclass(frozen=True)
class ChatTurn:
    """One question and its answer, as shown in the conversation."""

    question: str
    response: SupportResponse
    first_words_ms: int | None = None


def api_key() -> str | None:
    return st.session_state.get(API_KEY)


def unlock(key: str, available_models: tuple[str, ...]) -> None:
    """Keep an accepted key, and the models it may use, for this browser session."""
    st.session_state[API_KEY] = key
    st.session_state[AVAILABLE_MODELS] = available_models
    st.session_state.pop(FLASH, None)


def forget_key() -> None:
    """Remove the key and everything built from it or shown with it."""
    for name in _SESSION_KEYS:
        st.session_state.pop(name, None)


def available_models() -> tuple[str, ...]:
    return st.session_state.get(AVAILABLE_MODELS, ())


def support_session() -> SupportSession | None:
    return st.session_state.get(SUPPORT_SESSION)


def set_support_session(session: SupportSession) -> None:
    st.session_state[SUPPORT_SESSION] = session


def turns() -> list[ChatTurn]:
    return st.session_state.setdefault(TURNS, [])


def add_turn(turn: ChatTurn) -> None:
    turns().append(turn)


def drop_last_turn() -> ChatTurn | None:
    history = turns()
    return history.pop() if history else None


def clear_conversation() -> None:
    st.session_state[TURNS] = []
    session = support_session()
    if session is not None:
        session.reset()


def ask_later(question: str) -> None:
    """Queue a question (from an example button or "try again") for the next run."""
    st.session_state[PENDING_QUESTION] = question


def take_pending_question() -> str | None:
    return st.session_state.pop(PENDING_QUESTION, None)


def flash(kind: str, text: str) -> None:
    """A one-time message for the next run, such as "your key was removed"."""
    st.session_state[FLASH] = (kind, text)


def take_flash() -> tuple[str, str] | None:
    return st.session_state.pop(FLASH, None)


def ask_lock() -> threading.Lock:
    """Lets one answer finish before the next starts, if a visitor asks again mid-answer."""
    return st.session_state.setdefault(ASK_LOCK, threading.Lock())
