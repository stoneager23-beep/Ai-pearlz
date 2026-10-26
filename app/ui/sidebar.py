"""The sidebar: new conversation, model, filters, knowledge-base facts, the key and the cost."""

import streamlit as st

from app import services, state
from app.ui import components as ui
from app.ui.scene3d import COMPACT_HEIGHT, PearlState, pearl
from src.config import Settings, get_settings
from src.retrieval.shared_index import SharedIndex
from src.utils.api_keys import mask_secret

ALL_PRODUCTS = "All products"


def selected_model(settings: Settings) -> str:
    """The chosen chat model; the configured default if the key may use it."""
    models = state.available_models()
    default = settings.openai_chat_model if settings.openai_chat_model in models else models[0]
    return st.session_state.setdefault(state.MODEL_WIDGET, default)


def selected_doc_types() -> tuple[str, ...]:
    return tuple(st.session_state.get(state.DOC_TYPES_WIDGET, ()))


def selected_product_line() -> str | None:
    value = st.session_state.get(state.PRODUCT_WIDGET, ALL_PRODUCTS)
    return None if value == ALL_PRODUCTS else value


def _on_model_change() -> None:
    session, key = state.support_session(), state.api_key()
    if session is not None and key is not None:
        services.switch_model(session, get_settings(), key, st.session_state[state.MODEL_WIDGET])


def _on_filter_change() -> None:
    session = state.support_session()
    if session is not None:
        session.set_filters(doc_types=selected_doc_types(), product_line=selected_product_line())


def _remove_key() -> None:
    state.forget_key()
    state.flash("ok", "Your key was removed from this session.")


def render_sidebar(
    settings: Settings, index: SharedIndex, pearl_state: PearlState, *, show_pearl: bool
) -> None:
    key = state.api_key() or ""
    with st.sidebar:
        ui.show(ui.brand())
        if show_pearl:
            pearl(pearl_state, height=COMPACT_HEIGHT, key="pearl-side")
        st.button(
            "New conversation",
            icon=":material/add:",
            width="stretch",
            on_click=state.clear_conversation,
            disabled=not state.turns(),
        )

        ui.show(ui.side_label("Answer model"))
        options = {
            option.name: option
            for option in settings.chat_model_options()
            if option.name in state.available_models()
        }
        selected_model(settings)
        st.selectbox(
            "Answer model",
            list(options),
            key=state.MODEL_WIDGET,
            format_func=lambda name: options[name].label,
            on_change=_on_model_change,
            label_visibility="collapsed",
        )
        ui.show(
            '<p class="sp-footnote">'
            f"{ui.escape(ui.retirement_note(options[st.session_state[state.MODEL_WIDGET]]))}</p>"
        )

        ui.show(ui.side_label("Search in"))
        st.multiselect(
            "Document types",
            services.doc_types(settings),
            key=state.DOC_TYPES_WIDGET,
            format_func=lambda name: ui.DOC_TYPE_LABELS.get(name, name),
            placeholder="All document types",
            on_change=_on_filter_change,
            label_visibility="collapsed",
        )
        st.selectbox(
            "Product",
            [ALL_PRODUCTS, *services.product_lines(settings)],
            key=state.PRODUCT_WIDGET,
            on_change=_on_filter_change,
            label_visibility="collapsed",
        )

        ui.show(ui.side_label("Knowledge base") + ui.kb_stats(index.manifest))
        with st.expander("How this works"):
            ui.show(ui.how_it_works(settings.relevance_threshold, settings.retrieval_k))

        ui.show(ui.side_label("Your key"))
        ui.show(
            ui.note(
                "lock",
                f"{ui.escape(mask_secret(key))}, held in memory for this browser session only.",
            )
        )
        st.button("Change or remove key", width="stretch", on_click=_remove_key)
        spent = sum(turn.response.usage.total_tokens for turn in state.turns())
        ui.show(
            ui.note(
                "info",
                "Usage is billed to your own OpenAI account. "
                f"This conversation so far: {spent:,} tokens.",
            )
        )
