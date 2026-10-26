"""The key gate: the first screen, shown until the visitor's own OpenAI key is accepted.

The app has no key of its own, locally or deployed. The key is typed into a masked field
inside a form that clears on submit, checked (format first, then one tiny request), and only
then kept in this browser session's `st.session_state`. It is never written to disk, logged,
put in a URL or shown back; the copy below claims no more than that.
"""

import streamlit as st

from app import state
from app.ui import components as ui
from app.ui.scene3d import HERO_HEIGHT, PearlState, pearl
from src.config import Settings
from src.errors import PLATFORM_KEYS_URL
from src.llm.key_check import validate_api_key

# Measured in the evaluation run of 2026-10-26 (evaluation/results/eval_results.json):
# 1,444 to 2,683 tokens per answered question with gpt-4.1-mini, median about 1,760.
TYPICAL_TOKENS_PER_QUESTION = "1,500 to 2,700"


def render_gate(settings: Settings) -> None:
    pearl(PearlState.LOCKED, height=HERO_HEIGHT, key="pearl-hero")
    ui.show(
        ui.hero(
            "Pearlz Home · customer support",
            "Answers from our documents, with the page to prove it.",
            "Ask about AquaPearl purifiers, filters, warranty, returns and delivery. Every "
            "answer comes from Pearlz Home's own manuals and policies, with its sources.",
        )
    )

    flash = state.take_flash()
    with st.container(key="sp-gate-card"):
        ui.show(
            "<h3>Connect your OpenAI key</h3><p>This prototype runs on your own OpenAI "
            "account. Paste a key to start; it is checked with one tiny request first.</p>"
        )
        with st.form("sp-key-form", clear_on_submit=True, border=False):
            raw_key = st.text_input(
                "OpenAI API key",
                type="password",
                placeholder="sk-...",
                autocomplete="off",
                help="Create one at platform.openai.com, under API keys.",
            )
            submitted = st.form_submit_button("Unlock", type="primary", width="stretch")

        if submitted:
            with st.spinner("Checking your key..."):
                check = validate_api_key(raw_key, settings)
            if check.ok:
                state.unlock(raw_key.strip(), check.available_models)
                st.rerun()
            ui.show(ui.message("error", check.message))
        elif flash is not None:
            ui.show(ui.message(*flash))

        ui.show(
            ui.note(
                "lock",
                "Your key is held in memory for this browser session only and is never "
                "written to disk, logged or shared.",
            )
            + ui.note(
                "info",
                "Usage is billed to your own OpenAI account. A typical question uses about "
                f"{TYPICAL_TOKENS_PER_QUESTION} tokens.",
            )
            + ui.note(
                "external",
                f'<a href="{PLATFORM_KEYS_URL}" target="_blank" rel="noopener noreferrer">'
                "Get an API key</a>",
            )
        )

    ui.show(
        '<p class="sp-footnote sp-center">Pearlz Home and its products are fictional, '
        "made up for a course assignment.</p>"
    )
