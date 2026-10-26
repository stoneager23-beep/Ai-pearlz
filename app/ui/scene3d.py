"""The 3D pearl: a Three.js scene in a static Streamlit component.

The scene lives in `app/assets/pearl_scene/index.html` (three.js 0.185.0 from cdnjs, pinned).
It is declared once as a component, so on reruns Streamlit keeps the same iframe and only sends
it the new state: the pearl eases from one look to the next instead of reloading.

States: locked (key gate), idle (ready), thinking (answer on its way), answered, refused.
The scene caps the pixel ratio at 2, pauses when the tab is hidden or the pearl is scrolled
out of view, draws one still frame when the visitor prefers reduced motion, falls back to a
CSS pearl without WebGL, and disposes of its GPU resources when the page closes.
"""

from enum import StrEnum
from pathlib import Path

import streamlit.components.v1 as components

SCENE_DIR = Path(__file__).resolve().parent.parent / "assets" / "pearl_scene"
HERO_HEIGHT = 260
COMPACT_HEIGHT = 150

# Declared once at import; the component itself holds no user data.
_pearl_component = components.declare_component("pearl_scene", path=str(SCENE_DIR))


class PearlState(StrEnum):
    LOCKED = "locked"
    IDLE = "idle"
    THINKING = "thinking"
    ANSWERED = "answered"
    REFUSED = "refused"


def pearl(state: PearlState, *, height: int, key: str) -> None:
    """Show the pearl in `state`. Keep `key` stable so the scene persists across reruns."""
    _pearl_component(state=str(state), height=height, key=key, default=None)
