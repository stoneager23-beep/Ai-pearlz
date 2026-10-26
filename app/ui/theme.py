"""The design system: tokens defined once, and the stylesheet built from them.

Concept: a calm, premium "water and pearl" support site. Deep ink-navy surfaces, one luminous
pearl-aqua accent, warm off-white text, muted sand as the single secondary colour. Dark only,
done carefully: every text colour below meets WCAG AA contrast on the surfaces it is used on
(body text #F3EEE6 on #070B14 is about 17:1; muted text #8F97A8 about 6.5:1).

`inject_theme` writes the stylesheet once per page run. It also hides Streamlit's default
chrome and restyles the widgets the app uses, so nothing looks like a stock Streamlit app.
"""

from pathlib import Path

import streamlit as st

COLORS = {
    "ink-950": "#070B14",
    "ink-900": "#0B1220",
    "ink-850": "#0E1728",
    "ink-800": "#121D33",
    "ink-700": "#1B2842",
    "hairline": "rgba(226, 232, 240, 0.09)",
    "hairline-strong": "rgba(226, 232, 240, 0.18)",
    "text": "#F3EEE6",
    "text-soft": "#CFC8BC",
    "text-muted": "#8F97A8",
    "aqua": "#7FE3DA",
    "aqua-soft": "rgba(127, 227, 218, 0.12)",
    "aqua-line": "rgba(127, 227, 218, 0.35)",
    "aqua-ink": "#06231F",
    "sand": "#D9C29A",
    "sand-soft": "rgba(217, 194, 154, 0.12)",
    "slate": "#9AACBF",
    "slate-soft": "rgba(154, 172, 191, 0.12)",
}

FONTS = {
    "display": '"Fraunces", "Iowan Old Style", Georgia, serif',
    "body": '"Inter", system-ui, -apple-system, "Segoe UI", sans-serif',
    "mono": '"JetBrains Mono", ui-monospace, "SFMono-Regular", Consolas, monospace',
}

# Type scale: (size, line height) in px.
TYPE_SCALE = {
    "xs": (12, 16),
    "sm": (14, 20),
    "md": (16, 26),
    "lg": (20, 28),
    "xl": (30, 36),
    "2xl": (44, 48),
}
SPACE = {1: 4, 2: 8, 3: 12, 4: 16, 5: 24, 6: 32, 7: 48, 8: 64}
RADII = {"sm": 8, "md": 12, "lg": 18, "pill": 999}
ELEVATION = "0 1px 0 rgba(255, 255, 255, 0.04) inset, 0 18px 40px -20px rgba(0, 0, 0, 0.75)"
EASING = {"out": "cubic-bezier(0.22, 1, 0.36, 1)", "in-out": "cubic-bezier(0.65, 0, 0.35, 1)"}
DURATION = {"fast": 160, "base": 240, "slow": 320}
CONTENT_WIDTH = 820


def _tokens() -> str:
    lines = [f"--{name}: {value};" for name, value in COLORS.items()]
    lines += [f"--font-{name}: {value};" for name, value in FONTS.items()]
    for name, (size, line_height) in TYPE_SCALE.items():
        lines += [f"--text-{name}: {size}px;", f"--leading-{name}: {line_height}px;"]
    lines += [f"--space-{step}: {value}px;" for step, value in SPACE.items()]
    lines += [f"--radius-{name}: {value}px;" for name, value in RADII.items()]
    lines += [f"--ease-{name}: {value};" for name, value in EASING.items()]
    lines += [f"--dur-{name}: {value}ms;" for name, value in DURATION.items()]
    lines += [f"--elevation: {ELEVATION};", f"--content-width: {CONTENT_WIDTH}px;"]
    return ":root {" + "".join(lines) + "}"


STYLESHEET = Path(__file__).resolve().parent.parent / "assets" / "styles.css"


def inject_theme() -> None:
    """Add the design tokens and the stylesheet to the page.

    `st.html` with only a <style> element adds no visible block. (Markdown would end the HTML
    at the first blank line of the stylesheet and print the rest as text.) The fonts come from
    Google Fonts through `.streamlit/config.toml`.
    """
    st.html(f"<style>{_tokens()}{STYLESHEET.read_text(encoding='utf-8')}</style>")
