"""Task 09 evidence: a logged multi-turn conversation with follow-ups and a topic switch.

Runs the conversation from the manual's sample interaction (Sec 3.3), then switches topic:

1. "my aquapearl 500 keeps beeping three times and then stops"
2. "is that covered under warranty?"                       (pronoun-only follow-up)
3. "ok and can I get it delivered to Skardu by tomorrow?"  (follow-up, partly covered)
4. "Actually, what's your privacy policy on app data?"     (topic switch)

For each turn it records the original and rewritten question, the retrieved chunks and the
answer, and copies the session's own "turn" lines from the log file, which is what the manual
asks to see.

Usage:  python -m evaluation.experiments.conversation
Output: RESULTS_DIR/conversation_transcript.md
"""

import sys

from evaluation.experiments.common import run_timestamp, start_experiment, write_result
from src.chains.session import SupportSession
from src.config import ConfigError
from src.errors import describe_failure
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import load_or_build
from src.llm.clients import build_chat_model
from src.utils.api_keys import ApiKeyError
from src.utils.logging_setup import LOG_FILE_NAME

RESULT_FILE = "conversation_transcript.md"
TURNS = (
    "my aquapearl 500 keeps beeping three times and then stops",
    "is that covered under warranty?",
    "ok and can I get it delivered to Skardu by tomorrow?",
    "Actually, what's your privacy policy on app data?",
)


def main() -> int:
    try:
        context = start_experiment()
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1
    settings = context.settings
    try:
        index = load_or_build(settings, build_cached_embedder(context.api_key, settings))
        session = SupportSession(settings, index.store, build_chat_model(context.api_key, settings))
        responses = [session.ask(question) for question in TURNS]
    except Exception as error:  # an experiment run should end with a message, not a traceback
        print(describe_failure(error).message, file=sys.stderr)
        return 1

    lines = [
        "# Conversation transcript with query rewriting (Task 09)",
        "",
        f"Run: {run_timestamp()}. Session `{session.session_id}`, model `{session.model_name}`, "
        f"history window {settings.history_turns} turns, prompts {responses[0].prompt_version}.",
        "",
    ]
    for number, response in enumerate(responses, start=1):
        rewritten = response.standalone_question != response.original_question
        lines += [
            f"## Turn {number}",
            "",
            f"**Customer:** {response.original_question}",
            "",
            f"**Searched for:** {response.standalone_question}"
            + ("" if rewritten else " *(first turn or already standalone: not rewritten)*"),
            "",
            "**Retrieved:** "
            + ", ".join(f"`{chunk.chunk_id}` ({chunk.score:.3f})" for chunk in response.retrieved),
            "",
            f"**Assistant** ({response.confidence}): {response.answer}",
            "",
            *[f"- [{c.number}] {c.source} {c.location}" for c in response.sources],
            "",
        ]
    log_lines = [
        line.rstrip()
        for line in (settings.log_dir / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()
        if f'"session": "{session.session_id}"' in line
    ]
    lines += [
        "## The session's log lines (from logs/supportpearlz.log)",
        "",
        "```text",
        *log_lines,
        "```",
        "",
    ]
    path = write_result(settings, RESULT_FILE, "\n".join(lines))
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
