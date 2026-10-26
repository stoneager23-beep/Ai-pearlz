"""Conversation history and query condensation (Task 09).

Follow-ups such as "is that covered?" carry almost no searchable meaning on their own: their
embedding lands near nothing useful. Before retrieval, the model rewrites the latest message
into a standalone question using the recent conversation ("Is a replacement PF-1 filter
covered by the AquaPearl 500 Pro warranty?"). Retrieval then searches with that question.

History is bounded to the last HISTORY_TURNS question-and-answer pairs (a sliding window). The
window loses older turns completely, so a detail mentioned five turns ago is forgotten; in
exchange the rewrite prompt stays small and old topics cannot leak into new questions. Answers
are shortened in the transcript, because the rewrite needs what was discussed, not every word.

On the first turn there is no history, so the question is used as it is and no model call is
made.
"""

from collections import deque
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableBranch, RunnableLambda

from src.chains.prompts import condense_prompt

# Characters of each earlier answer kept in the rewrite transcript.
ANSWER_CHARACTERS_IN_TRANSCRIPT = 400
CONDENSE_TAG = "condense"


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str


class ConversationMemory:
    """The last `max_turns` turns of one session."""

    def __init__(self, max_turns: int) -> None:
        self._turns: deque[Turn] = deque(maxlen=max_turns)

    def add(self, question: str, answer: str) -> None:
        if self._turns.maxlen:
            self._turns.append(Turn(question, answer))

    def reset(self) -> None:
        self._turns.clear()

    @property
    def turns(self) -> list[Turn]:
        return list(self._turns)


def transcript(turns: list[Turn]) -> str:
    """The turns as plain text for the rewrite prompt, with long answers shortened."""
    lines = []
    for turn in turns:
        answer = turn.answer
        if len(answer) > ANSWER_CHARACTERS_IN_TRANSCRIPT:
            answer = answer[:ANSWER_CHARACTERS_IN_TRANSCRIPT].rsplit(" ", 1)[0] + " ..."
        lines += [f"Customer: {turn.question}", f"Assistant: {answer}"]
    return "\n".join(lines)


def _clean_rewrite(inputs: dict) -> str:
    rewritten = inputs["rewritten"].strip().strip('"').strip()
    return rewritten or inputs["question"]


def build_condenser(chat_model: BaseChatModel, prompt_version: str) -> Runnable:
    """A runnable from {"question", "history"} to the standalone question."""
    rewrite = (
        RunnableLambda(
            lambda inputs: {
                "history": transcript(inputs["history"]),
                "question": inputs["question"],
            }
        )
        | condense_prompt(prompt_version)
        | chat_model.with_config(tags=[CONDENSE_TAG])
        | StrOutputParser()
    )
    with_fallback = {
        "rewritten": rewrite,
        "question": lambda inputs: inputs["question"],
    } | RunnableLambda(_clean_rewrite)
    return RunnableBranch(
        (lambda inputs: not inputs["history"], lambda inputs: inputs["question"]),
        with_fallback,
    )
