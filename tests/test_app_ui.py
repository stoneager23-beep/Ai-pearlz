"""The web interface: safe markup, the key gate, and the theme. No network, no real key."""

import os
import tomllib

import pytest
from streamlit.testing.v1 import AppTest

from app.state import ChatTurn
from app.ui import components as ui
from app.ui.conversation import pearl_state_for
from app.ui.scene3d import PearlState
from app.ui.theme import COLORS, FONTS
from src.chains.schemas import (
    Citation,
    Confidence,
    GateInfo,
    RefusalReason,
    RetrievedChunk,
    SupportResponse,
)
from src.config import PROJECT_ROOT

APP_FILE = str(PROJECT_ROOT / "streamlit_app.py")
INJECTION = '<img src=x onerror="alert(1)">'


def _response(**overrides: object) -> SupportResponse:
    values = {
        "answer": "The warranty is 24 months [1].",
        "confidence": Confidence.HIGH,
        "answered": True,
        "original_question": "How long is the warranty?",
        "standalone_question": "How long is the warranty?",
        "model": "gpt-4.1-mini",
        "prompt_version": "v2+c2",
        "gate": GateInfo(passed=True, best_score=0.77, threshold=0.34, reason="ok"),
        "retrieved": [
            RetrievedChunk(
                label="S1",
                chunk_id="warranty_policy.md::0002",
                source="warranty_policy.md",
                location="§2. Warranty periods",
                score=0.77,
            )
        ],
        "sources": [
            Citation(
                number=1,
                source="warranty_policy.md",
                doc_title="Warranty Policy",
                location="§2. Warranty periods",
                snippet="The AquaPearl 500 Pro is covered for 24 months.",
                labels=["S1"],
                chunk_ids=["warranty_policy.md::0002"],
            )
        ],
    }
    values.update(overrides)
    return SupportResponse(**values)


def test_answer_markup_escapes_html_and_styles_references():
    markup = ui.answer_markup(f"Costs $5 {INJECTION} [1][2].")

    assert "<img" not in markup
    assert "&lt;img" in markup
    assert r"\$5" in markup
    assert markup.count('class="sp-ref"') == 2


def test_source_cards_escape_document_text():
    citation = _response().sources[0].model_copy(update={"snippet": INJECTION})

    markup = ui.source_cards([citation])

    assert "<img" not in markup
    assert "Warranty Policy" in markup


def test_inspector_shows_the_pipeline_and_escapes_the_question(fake_key):
    response = _response(original_question=INJECTION, standalone_question="warranty period")

    markup = ui.inspector(ChatTurn(INJECTION, response, first_words_ms=900))

    assert "<img" not in markup
    assert "rewritten from the conversation" in markup
    assert "0.770" in markup
    assert "first words after 0.9 s" in markup
    assert fake_key not in markup


def test_refusal_card_offers_the_support_email():
    response = _response(
        answer="I won't guess.", answered=False, refusal_reason=RefusalReason.GATE, sources=[]
    )

    markup = ui.refusal_card(response, "support@pearlzhome.example or 0800-73275")

    assert 'href="mailto:support@pearlzhome.example"' in markup
    assert "Not covered by our documents" in markup


def test_pearl_state_follows_the_conversation():
    answered = ChatTurn("q", _response())
    refused = ChatTurn("q", _response(refusal_reason=RefusalReason.MODEL, answered=False))

    assert pearl_state_for([], asking=False) is PearlState.IDLE
    assert pearl_state_for([answered], asking=True) is PearlState.THINKING
    assert pearl_state_for([answered], asking=False) is PearlState.ANSWERED
    assert pearl_state_for([answered, refused], asking=False) is PearlState.REFUSED


def test_streamlit_theme_matches_the_design_tokens():
    config = tomllib.loads((PROJECT_ROOT / ".streamlit" / "config.toml").read_text("utf-8"))
    theme = config["theme"]

    assert theme["primaryColor"] == COLORS["aqua"]
    assert theme["backgroundColor"] == COLORS["ink-950"]
    assert theme["secondaryBackgroundColor"] == COLORS["ink-850"]
    assert theme["textColor"] == COLORS["text"]
    assert theme["sidebar"]["backgroundColor"] == COLORS["ink-900"]
    for setting, token in (("font", "body"), ("headingFont", "display"), ("codeFont", "mono")):
        family = theme[setting].split(":", 1)[0]
        assert FONTS[token].startswith(f'"{family}"')
    assert config["client"]["showErrorDetails"] == "none"


def test_secrets_example_holds_no_key():
    text = (PROJECT_ROOT / ".streamlit" / "secrets.toml.example").read_text("utf-8")

    assert "sk-" not in text
    assert all(line.startswith("#") or not line.strip() for line in text.splitlines())


@pytest.fixture
def app(monkeypatch):
    monkeypatch.chdir(PROJECT_ROOT)
    return AppTest.from_file(APP_FILE, default_timeout=60)


def test_gate_is_shown_even_when_the_server_has_a_key(app, monkeypatch, fake_key):
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)

    app.run()

    assert not app.exception
    assert [field.label for field in app.text_input] == ["OpenAI API key"]
    assert "sp_api_key" not in app.session_state
    assert "OPENAI_API_KEY" not in os.environ


def test_gate_rejects_a_malformed_key_without_storing_it(app):
    app.run()
    app.text_input[0].input("not-a-key")
    app.button[0].click().run()

    assert not app.exception
    assert any("look like an OpenAI API key" in block.value for block in app.markdown)
    assert "sp_api_key" not in app.session_state


def test_page_source_never_contains_the_key(app, fake_key):
    app.run()
    app.text_input[0].input(fake_key[:12])  # too short: rejected by the format check
    app.button[0].click().run()

    page = " ".join(block.value for block in app.markdown)
    assert fake_key[:12] not in page


def test_stylesheet_keeps_the_button_that_reopens_the_sidebar():
    css = (PROJECT_ROOT / "app" / "assets" / "styles.css").read_text("utf-8")
    hidden = [rule.split("{")[0] for rule in css.split("}") if "display: none" in rule]

    for testid in ("stHeader", "stToolbar", "stExpandSidebarButton"):
        assert not any(f'"{testid}"' in selectors for selectors in hidden), testid
