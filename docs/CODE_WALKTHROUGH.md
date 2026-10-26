# Code walkthrough

One section per task. Each section says what every new file does, why it is built that way,
which viva questions (manual Sec 12) it prepares you for, and how to answer them using this
codebase's own names and numbers. Where something is non-obvious or provisional, it says so.

---

## T01: Project setup and configuration

### What the manual asks for

A reproducible skeleton: packages in the Sec 3.4 layout, a virtual environment with the Python
version recorded, pinned requirements, `.env.example`, a `.gitignore`, one validated settings
object that fails loudly and clearly, and central logging with console and file handlers.

Acceptance: `python -m src.config` prints the configuration with secrets masked, and removing
a required variable produces one clear error message.

### Files

| File | What it does |
|---|---|
| `src/config.py` | Defines `Settings`, the one object holding every tunable. Reads env vars, then `.env`, then defaults. Validates everything. `python -m src.config` is the smoke check. |
| `src/utils/api_keys.py` | Everything about the OpenAI key that needs no network: format check (`check_key_format`), masking (`mask_secret`), redaction (`redact_api_keys`), and how CLI tools find the key (`resolve_cli_api_key`). |
| `src/utils/logging_setup.py` | `configure_logging(settings)`: one stdout handler, one rotating file handler, both carrying `ApiKeyRedactionFilter`. |
| `.env.example` | Every variable the project reads, its default, and a one-line comment. |
| `.gitignore` | Keeps out `.env`, Streamlit secrets, the vector store, logs, caches and the manual PDF. |
| `.gitattributes` | Stores text files with LF line endings, so the repository is identical on Windows and Linux. |
| `requirements.in` / `requirements.txt` | The packages we chose / the exact versions of those plus everything they depend on. |
| `requirements-dev.in` / `requirements-dev.txt` | Adds pytest and ruff, pinned to match the runtime lock. |
| `pyproject.toml` | ruff rules (including "type hints required", "no print", "no commented-out code") and pytest settings. |
| `src/*/__init__.py` | Make the folders Python packages. Each holds a one-line description of its package. |
| `tests/conftest.py` | Removes every config variable and the key from the environment before each test, so a real `.env` can never affect a result. |
| `tests/test_config.py` | 16 tests: defaults, env overrides, every validation rule, immutability, the smoke check's three outcomes. |
| `tests/test_api_keys.py` | 22 tests: each key-format rule, masking, redaction, where CLI tools get the key, and when they may prompt. |
| `tests/test_logging_redaction.py` | 5 tests: a key logged by our code, by a library, inside a traceback, or while a handler is failing never reaches stdout, stderr or the file. |
| `tests/test_env_example.py` | 2 tests: `.env.example` lists exactly the variables `Settings` reads, and its values equal the defaults. |

### Design decisions and why

1. **The API key is not a setting.** `Settings` holds tunables only. It is printed by the smoke
   check, logged, and (later) shared by every Streamlit visitor through `get_settings()`. A key
   belongs to one person, so it never lives in a shared object. CLI tools get it from
   `resolve_cli_api_key`; the Streamlit app will get it from the key screen into
   `st.session_state`. `test_settings_never_hold_the_api_key` proves it.

2. **`.env` is read without copying it into `os.environ`.** The OpenAI SDK automatically uses
   `OPENAI_API_KEY` from the environment if a client is built without an explicit key. If we
   called `load_dotenv()`, a developer's key in `.env` would silently power the Streamlit app
   and bypass the key screen. So pydantic-settings reads tunables straight from the file, and
   `dotenv_values()` reads the key for CLI tools only. Test:
   `test_env_file_key_is_used_without_touching_os_environ`.

3. **Defaults live in exactly one place.** Every default is in `Settings`. `.env.example` shows
   the same values for people reading it, and `test_documented_values_are_the_defaults` loads
   the settings from `.env.example` and checks they equal the built-in defaults, so the two
   can never drift apart.

4. **Settings are frozen and loaded once.** `get_settings()` is wrapped in `lru_cache`, so the
   environment is read once per process. `frozen=True` means nothing can change a setting after
   loading, which matters once many Streamlit sessions share the same object.

5. **One readable error, not a traceback.** `load_settings` turns pydantic's `ValidationError`
   into a `ConfigError` whose message names each bad variable in upper case, the way you typed
   it. Cross-field rules are checked too: `CHUNK_OVERLAP` must be smaller than `CHUNK_SIZE`, and
   `OPENAI_CHAT_MODEL` must be one of `OPENAI_CHAT_MODELS`.

6. **Temperature is capped at 0.3** (`MAX_TEMPERATURE`). The manual requires a low, explicit
   temperature. Any value above the cap is rejected at startup rather than discovered later as
   unrepeatable evaluation results.

7. **A small model catalogue.** `CHAT_MODEL_CATALOGUE` lists the chat models users may pick:
   `gpt-4.1-mini` (default), `gpt-4.1`, `gpt-4o-mini`, `gpt-4o`. All four are non-reasoning models,
   so they accept `temperature=0`. Newer OpenAI models are reasoning models whose
   temperature support is undocumented or absent, so they are left out. Each entry records
   OpenAI's announced retirement date (2027-01-14) so the interface can show it. Model names
   appear nowhere else in the code (manual mistake #10).

8. **Relative paths are resolved from the project root**, so commands work no matter which
   folder you run them from.

9. **The redaction filter sits on the handlers, not on a logger.** A filter on a logger only
   sees records created on that exact logger, so a key inside an `openai` or `httpx` message
   would slip past it. Every record that gets written goes through a handler, so a
   handler filter catches all of them. It redacts the message, the traceback and the stack.

10. **`logging.raiseExceptions = False`.** Found while testing: when a log handler itself fails
    (closed stream, full disk), Python's logging prints the original exception straight to
    stderr, skipping every filter, so the raw key appeared there. Turning the flag off makes
    such failures silent. `test_failing_handler_does_not_print_the_raw_exception` guards it.

11. **Logging can be configured repeatedly without duplicating lines.** Streamlit re-runs the
    whole script on every click. `configure_logging` replaces its own named handlers instead
    of adding more.

12. **Logs go to stdout and a file.** Streamlit Cloud wipes its disk on restart but keeps stdout,
    so stdout is the durable copy there; locally the file is easier to read later.

13. **CLI tools prompt only when stdin and stdout are both terminals.** Found while testing: on
    Windows, stdin redirected from `NUL` still reports `isatty() == True`, and `getpass` then
    waited forever. Requiring both streams to be terminals fixes it.

14. **Two-level requirements.** `requirements.in` lists what we chose; `requirements.txt` is
    the generated lock with every package at an exact version. It is compiled with
    `--universal` because the lock is made on Windows but Streamlit Cloud runs Linux. A clean
    virtual environment built from `requirements.txt` alone ran the smoke check successfully
    (82 packages).

15. **`langchain-community` is used even though it was archived in June 2026.** The manual
    names it, and the FAISS store and the PDF, CSV and text loaders exist only there. The PyPI
    package called `langchain-faiss` is an unofficial 2024 upload by an unrelated author, so it
    was rejected. The pinned 0.4.2 works; the limitation is recorded in the README.

### Provisional values (not evidence yet)

`CHUNK_SIZE=800`, `CHUNK_OVERLAP=120`, `RETRIEVAL_K=4` and `RELEVANCE_THRESHOLD=0.30` are starting
points only. T03 replaces the chunking values and T06 the retrieval values with numbers from
experiments on this knowledge base. Do not quote them in the viva as chosen values until then.

### Viva questions this task prepares

- **Q15: Why does temperature matter, and what would you set it to?** "Temperature controls
  how random the model's word choice is. We answer from documents, so we want the same question
  to give the same facts and citations every time; that is also what makes our evaluation
  repeatable. `LLM_TEMPERATURE` defaults to 0 and `src/config.py` rejects anything above 0.3
  at startup. I would only allow more for purely stylistic text produced separately from the
  facts, which this system does not have."

- **Q4: Why must the same embedding model be used for indexing and querying?** (Partly here.)
  "There is one setting, `OPENAI_EMBEDDING_MODEL`, used by both the index build and the query
  path, so they cannot differ by accident. In T05 the index also records which model built it,
  and startup refuses to query an index built with a different model."

- **Code-quality follow-up: "How would you change k or the model?"** "Set `RETRIEVAL_K` or
  `OPENAI_CHAT_MODEL` in `.env`. No code changes. `python -m src.config` shows the values in
  use, and an invalid value stops the program with a message naming the variable."

### Evidence (real output, 2026-10-26)

```text
$ python -m src.config      # fresh copy of .env.example, key left empty, no terminal
OPENAI_API_KEY is not set. Add it to .env, or run this command in a terminal to enter it with hidden input.
(exit code 1)

$ CHUNK_OVERLAP=900 python -m src.config
Configuration error (check .env or your environment variables):
  - CHUNK_OVERLAP (900) must be smaller than CHUNK_SIZE (800)
(exit code 1)

$ OPENAI_API_KEY=<fake key> python -m src.config
SupportPearlz configuration
  LLM_PROVIDER            openai
  OPENAI_CHAT_MODEL       gpt-4.1-mini
  ...
  OPENAI_API_KEY          sk-******** (set, masked)
(exit code 0)
```

`ruff check`: all checks passed. `pytest`: 45 passed.
