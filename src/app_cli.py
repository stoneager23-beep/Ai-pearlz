"""Interactive command-line chat with SupportPearlz.

Usage:
    python -m src.app_cli [--model gpt-4.1-mini] [--product "AquaPearl 300"] [--doc-type policy]

Commands inside the chat:
    /reset    start a new conversation (forget the history)
    /model    show or change the chat model, e.g. "/model gpt-4o"
    /verbose  show or hide what happened behind each answer (rewrite, chunks, scores, tokens)
    /help     show the commands
    /quit     leave (Ctrl+C or Ctrl+D also work)

The OpenAI key comes from OPENAI_API_KEY in the environment or .env, or a hidden prompt. The
index is loaded from disk, and built first only if it is missing or out of date.
"""

import argparse
import logging
import sys
import textwrap

from src.chains.schemas import SupportResponse
from src.chains.session import SupportSession
from src.config import DEFAULT_ENV_FILE, ConfigError, Settings, get_settings
from src.errors import describe_failure, log_detail
from src.ingestion.embedding_cache import build_cached_embedder
from src.ingestion.indexing import load_or_build
from src.llm.clients import build_chat_model
from src.utils.api_keys import ApiKeyError, interactive_prompt, resolve_cli_api_key
from src.utils.logging_setup import configure_logging

WRAP_WIDTH = 92
INDENT = " " * 7
HELP = """Commands: /reset (new conversation), /model [name], /verbose, /help, /quit"""

logger = logging.getLogger(__name__)


def _wrap(text: str) -> str:
    paragraphs = [
        textwrap.fill(line, WRAP_WIDTH, initial_indent=INDENT, subsequent_indent=INDENT)
        for line in text.splitlines()
        if line.strip()
    ]
    return "\n".join(paragraphs).lstrip()


def render_response(response: SupportResponse, verbose: bool) -> str:
    """The answer, its sources and its confidence, as plain text for the terminal."""
    lines = [f"Bot  > {_wrap(response.answer)}"]
    if response.sources:
        lines.append(f"{INDENT}Sources:")
        for citation in response.sources:
            location = f", {citation.location}" if citation.location else ""
            lines.append(f"{INDENT}  [{citation.number}] {citation.source}{location}")
            lines.append(f'{INDENT}      "{citation.snippet}"')
    elif not response.answered:
        lines.append(f"{INDENT}Sources: none (no supporting source was found)")
    lines.append(f"{INDENT}Confidence: {response.confidence}")
    if response.standalone_question != response.original_question:
        lines.append(f"{INDENT}(searched for: {response.standalone_question})")
    if verbose:
        lines.extend(_behind_the_answer(response))
    return "\n".join(lines)


def _behind_the_answer(response: SupportResponse) -> list[str]:
    lines = [f"{INDENT}--- behind the answer ---"]
    if response.gate:
        verdict = "passed" if response.gate.passed else "refused"
        lines.append(f"{INDENT}gate: {verdict}, {response.gate.reason}")
    for chunk in response.retrieved:
        label = f"[{chunk.label}] " if chunk.label else ""
        lines.append(f"{INDENT}{chunk.score:.3f} {label}{chunk.chunk_id}  {chunk.location}")
    if response.invalid_citations:
        lines.append(f"{INDENT}dropped invalid citations: {', '.join(response.invalid_citations)}")
    lines.append(
        f"{INDENT}model {response.model}, prompt {response.prompt_version}, "
        f"tokens {response.usage.input_tokens} in / {response.usage.output_tokens} out, "
        f"{response.latency_ms} ms"
    )
    return lines


def _start_session(args: argparse.Namespace, settings: Settings, api_key: str) -> SupportSession:
    index = load_or_build(settings, build_cached_embedder(api_key, settings))
    session = SupportSession(
        settings,
        index.store,
        build_chat_model(api_key, settings, args.model),
        doc_types=tuple(args.doc_type or ()),
        product_line=args.product,
    )
    manifest = index.manifest
    print(
        f"[Session started | knowledge base: {settings.collection_name} | {manifest.chunk_count} "
        f"chunks | {len(manifest.file_fingerprints)} documents | model {session.model_name} | "
        f"session {session.session_id}]"
    )
    return session


def _handle_command(command: str, session: SupportSession, state: dict, api_key: str) -> bool:
    """Run a /command. Returns False when the user wants to quit."""
    name, _, argument = command.partition(" ")
    if name in ("/quit", "/exit"):
        return False
    if name == "/reset":
        session.reset()
        print("New conversation started.")
    elif name == "/verbose":
        state["verbose"] = not state["verbose"]
        print(f"Behind-the-answer details {'on' if state['verbose'] else 'off'}.")
    elif name == "/model" and argument:
        try:
            session.chat_model = build_chat_model(api_key, session.settings, argument.strip())
        except ValueError:
            print(f"Choose one of: {', '.join(session.settings.openai_chat_models)}")
        else:
            session.set_filters(doc_types=session.doc_types, product_line=session.product_line)
            print(f"Model changed to {session.model_name}.")
    elif name == "/model":
        available = ", ".join(session.settings.openai_chat_models)
        print(f"Model: {session.model_name}. Available: {available}")
    else:
        print(HELP)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat with the SupportPearlz assistant.")
    parser.add_argument("--model", help="Chat model (one of OPENAI_CHAT_MODELS)")
    parser.add_argument(
        "--product", help='Only use documents for this product line, e.g. "AquaPearl 300"'
    )
    parser.add_argument(
        "--doc-type", action="append", help="Only use this document type (repeatable)"
    )
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        configure_logging(settings)
        api_key = resolve_cli_api_key(DEFAULT_ENV_FILE, prompt=interactive_prompt())
        session = _start_session(args, settings, api_key)
    except (ConfigError, ApiKeyError) as error:
        print(error, file=sys.stderr)
        return 1
    except Exception as error:  # start-up failures (index build, network) end with a message
        logger.error("Start-up failed: %s", log_detail(error), exc_info=True)
        print(f"Could not start. {describe_failure(error).message}", file=sys.stderr)
        return 1

    print(HELP)
    state = {"verbose": False}
    while True:
        try:
            question = input("\nYou  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        if question.startswith("/"):
            if not _handle_command(question, session, state, api_key):
                return 0
            continue
        print(render_response(session.ask(question), state["verbose"]))


if __name__ == "__main__":
    sys.exit(main())
