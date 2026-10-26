"""One run of the SupportPearlz page, top to bottom.

1. Gate: until this browser session has an accepted key, only the key screen is shown.
2. Index: the shared, key-free index is loaded (or, on a fresh server, built once with the
   visitor's key, behind the build lock, with an honest estimate of what it costs).
3. Session: this visitor's own SupportSession (their key, their clients, their memory).
4. Page: the empty state with example questions, or the conversation, plus the sidebar.
"""

import logging
import os
from pathlib import Path

import streamlit as st

from app import services, state
from app.ui import components as ui
from app.ui.conversation import (
    answer_new_question,
    pearl_state_for,
    render_empty_state,
    render_hero_pearl,
    render_turns,
)
from app.ui.gate import render_gate
from app.ui.sidebar import (
    render_sidebar,
    selected_doc_types,
    selected_model,
    selected_product_line,
)
from app.ui.theme import inject_theme
from src.chains.session import SupportSession
from src.config import ConfigError, Settings, get_settings
from src.errors import describe_failure, log_detail
from src.ingestion.indexing import estimate_build, index_is_current
from src.retrieval.shared_index import SharedIndex
from src.utils.api_keys import API_KEY_ENV_VAR
from src.utils.logging_setup import configure_logging

PAGE_ICON = Path(__file__).resolve().parent / "assets" / "favicon.png"
CHAT_INPUT_MAX_CHARS = 1000

logger = logging.getLogger(__name__)


def _settings() -> Settings | None:
    try:
        # Top-level secrets become environment variables, which src/config.py reads.
        st.secrets.load_if_toml_exists()
        return get_settings()
    except ConfigError as error:
        ui.show(ui.message("error", f"The app's configuration is invalid: {error}"))
    except Exception:  # a malformed secrets.toml; its content is not shown
        logger.exception("Could not read the Streamlit secrets")
        ui.show(ui.message("error", "The app's secrets could not be read."))
    return None


def _build_index(settings: Settings, api_key: str) -> bool:
    with st.status("Preparing the knowledge base", expanded=True) as status:
        try:
            estimate = estimate_build(settings)
            ui.show(
                ui.note(
                    "info",
                    "A one-time step on this server, using your key: "
                    f"{estimate.documents} documents in {estimate.chunks} chunks, roughly "
                    f"{estimate.tokens:,} tokens of embeddings. Chunks embedded before are "
                    "reused from the cache. Anyone arriving meanwhile waits for this build.",
                )
            )
            result = services.build_index_with_key(settings, api_key)
        except Exception as error:  # every failure becomes a readable message
            logger.warning("Index build failed: %s", log_detail(error))
            status.update(label="The knowledge base could not be prepared", state="error")
            ui.show(ui.message("error", describe_failure(error).message))
            st.button("Try again")
            return False
        status.update(
            label=(
                f"Knowledge base ready: {result.texts_embedded} chunks embedded "
                f"({result.tokens_embedded:,} tokens) in {result.seconds:.1f} s"
            ),
            state="complete",
            expanded=False,
        )
    return True


def _ready_index(settings: Settings, api_key: str) -> SharedIndex | None:
    version = st.session_state.get(state.INDEX_KEY)
    try:
        if version is None:
            if not index_is_current(settings) and not _build_index(settings, api_key):
                return None
            version = services.index_version(settings)
            st.session_state[state.INDEX_KEY] = version
        return services.shared_index(settings, version)
    except Exception as error:  # a missing or mismatched index on disk
        logger.warning("Index load failed: %s", log_detail(error))
        ui.show(ui.message("error", describe_failure(error).message))
        return None


def _ready_session(settings: Settings, index: SharedIndex, api_key: str) -> SupportSession:
    session = state.support_session()
    if session is None:
        session = services.new_support_session(
            settings,
            index,
            api_key,
            selected_model(settings),
            doc_types=selected_doc_types(),
            product_line=selected_product_line(),
        )
        state.set_support_session(session)
    return session


def run() -> None:
    st.set_page_config(page_title="SupportPearlz", page_icon=str(PAGE_ICON), layout="centered")
    inject_theme()
    settings = _settings()
    if settings is None:
        return
    configure_logging(settings)
    # The app never uses a key of its own: one left in the environment or secrets is dropped.
    os.environ.pop(API_KEY_ENV_VAR, None)

    api_key = state.api_key()
    if api_key is None:
        render_gate(settings)
        return

    question = (
        st.chat_input(
            "Ask about your purifier, filters, warranty or delivery",
            max_chars=CHAT_INPUT_MAX_CHARS,
        )
        or state.take_pending_question()
    )
    turns = state.turns()
    in_conversation = bool(turns) or question is not None
    if not in_conversation:
        render_hero_pearl()  # same place and key as the gate's pearl, so it animates on unlock

    index = _ready_index(settings, api_key)
    if index is None:
        return
    session = _ready_session(settings, index, api_key)
    render_sidebar(
        settings,
        index,
        pearl_state_for(turns, asking=question is not None),
        show_pearl=in_conversation,
    )

    if not in_conversation:
        render_empty_state(services.product_lines(settings))
        return
    render_turns(turns, settings)
    if question is not None:
        answer_new_question(question, session, len(turns))
