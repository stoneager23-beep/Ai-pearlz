"""Stream the answer text while the structured answer is still being written (bonus C4).

The answer model returns JSON (`AnswerDraft`), streamed token by token. This callback handler
watches only the answer model's run (tagged "answer"), re-parses the growing JSON with
LangChain's partial-JSON parser after every token, and queues each new piece of the `answer`
field. Citations and confidence are shown only when the whole object has arrived and been
validated, as the manual asks.

While streaming, the raw context labels ([S2]) are hidden: they are renumbered into [1], [2]
only after the citations are validated. A label that is still arriving ("[S") is held back
until it is complete, so text never appears and then disappears.
"""

import re
import time
from queue import Queue
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.utils.json import parse_partial_json

from src.chains.rag_chain import ANSWER_TAG

_LABELS = re.compile(r"\s*\[\s*S\d+(?:\s*,\s*S\d+)*\s*\]")


def displayable(answer_so_far: str) -> str:
    """The part of a partial answer that can be shown now, without raw [S1] labels.

    Trailing whitespace is held back too: the space before a label disappears with the label,
    and text already shown must always stay a prefix of what is shown next.
    """
    opening = answer_so_far.rfind("[")
    if opening != -1 and "]" not in answer_so_far[opening:]:
        answer_so_far = answer_so_far[:opening]
    return _LABELS.sub("", answer_so_far).rstrip()


class AnswerTextStream(BaseCallbackHandler):
    """Collects the answer field's text as it streams, as a queue of new pieces."""

    def __init__(self) -> None:
        self.pieces: Queue[str] = Queue()
        self.first_piece_at: float | None = None
        self._answer_runs: set[UUID] = set()
        self._json_by_run: dict[UUID, str] = {}
        self._shown = ""

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        if ANSWER_TAG in (tags or []):
            self._answer_runs.add(run_id)

    def on_llm_new_token(self, token: str, *, run_id: UUID, **kwargs: Any) -> None:
        if run_id not in self._answer_runs:
            return
        self._json_by_run[run_id] = self._json_by_run.get(run_id, "") + token
        parsed = parse_partial_json(self._json_by_run[run_id])
        answer = parsed.get("answer") if isinstance(parsed, dict) else None
        if not isinstance(answer, str):
            return
        visible = displayable(answer)
        if len(visible) > len(self._shown) and visible.startswith(self._shown):
            self.pieces.put(visible[len(self._shown) :])
            self._shown = visible
            if self.first_piece_at is None:
                self.first_piece_at = time.perf_counter()
