# SupportPearlz

A retrieval-augmented customer-support assistant for the fictional Pearlz Home Systems, built
with Python and LangChain for AAI-407 / PRAC-03. It answers questions about Pearlz water and air
purifiers strictly from the company's own documents, cites the exact page or section it used,
and says plainly when the documents do not contain the answer.

There are two ways to use it: an interactive command-line chat, and a Streamlit web app where
each visitor uses their own OpenAI API key.

## Build status

The project is built task by task, following the assignment manual. This README grows with it.

| Task | Topic | Status |
|---|---|---|
| T01 | Project setup and configuration | Done |
| T02 | Document ingestion | Not started |
| T03 | Chunking strategy | Not started |
| T04 | Embeddings | Not started |
| T05 | Vector store | Not started |
| T06 | Retriever comparison and relevance gate | Not started |
| T07 | The RAG chain | Not started |
| T08 | Prompt engineering for grounding | Not started |
| T09 | Conversational memory and follow-ups | Not started |
| T10 | Source attribution | Not started |
| T11 | Evaluation | Not started |
| — | Streamlit app and deployment | Not started |

## Prerequisites

- **Python 3.11.** Developed and tested with CPython 3.11.17. The manual accepts 3.10-3.12.
- **uv** (recommended) or pip, to create the virtual environment and install pinned packages.
- **An OpenAI API key**, only for commands that call OpenAI. Nothing in setup needs one.

## Setup

```bash
# 1. Install uv and Python 3.11 (skip if you already have them)
python -m pip install --user uv
python -m uv python install 3.11

# 2. Create and activate a virtual environment
python -m uv venv --python 3.11 .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # macOS / Linux

# 3. Install the pinned packages (the -dev file adds pytest and ruff)
python -m uv pip install -r requirements-dev.txt

# 4. Create your local configuration
copy .env.example .env            # Windows
cp .env.example .env              # macOS / Linux

# 5. Smoke check: prints every setting, with the key masked
python -m src.config
```

If the project folder is inside OneDrive, Dropbox or iCloud, create the virtual environment
outside it (for example `python -m uv venv --python 3.11 %USERPROFILE%\.venvs\supportpearlz`),
or the sync client will try to upload thousands of package files.

## The OpenAI API key

- **Streamlit app:** always asks the visitor for their own key, locally and when deployed. It
  never reads a key from `.env`, the environment or Streamlit secrets.
- **Command-line tools** (chat, index build, evaluation): read `OPENAI_API_KEY` from the
  environment or `.env`. If it is missing and you are at a terminal, they ask for it with
  hidden input. If it is missing and nobody is at a terminal, they stop with one clear message.
- The key is never stored in the shared settings object and never written to logs. Any text
  shaped like a key is replaced with `sk-[REDACTED]` before it reaches stdout or the log file.
- `.env` is git-ignored. Never commit it.

## Configuration

Every setting is read in `src/config.py` and nowhere else. Change it with an environment
variable or a line in `.env`. On Streamlit Community Cloud, add it as a top-level entry in the
app's secrets. Invalid values stop the program with one message naming the variable.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | *(empty)* | Key for command-line tools only. See above. |
| `LLM_PROVIDER` | `openai` | Provider of the chat and embedding models. Only `openai` is implemented. |
| `OPENAI_CHAT_MODEL` | `gpt-4.1-mini` | Chat model used when nobody picks one. |
| `OPENAI_CHAT_MODELS` | `gpt-4.1-mini,gpt-4.1,gpt-4o-mini,gpt-4o` | Chat models users may pick from. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model for indexing and querying. Changing it needs a full rebuild. |
| `LLM_TEMPERATURE` | `0` | Sampling temperature, 0 to 0.3. |
| `KNOWLEDGE_BASE_DIR` | `data/knowledge_base` | Folder of source documents. |
| `VECTOR_STORE_DIR` | `data/vector_store` | Where the index is saved (git-ignored). |
| `COLLECTION_NAME` | `pearlz_kb` | Name of the index inside `VECTOR_STORE_DIR`. |
| `CHUNK_SIZE` | `800` | Maximum characters per chunk. Provisional until the T03 experiment. |
| `CHUNK_OVERLAP` | `120` | Characters shared by neighbouring chunks. Provisional until T03. |
| `RETRIEVAL_K` | `4` | Chunks retrieved per question. Provisional until T06. |
| `RELEVANCE_THRESHOLD` | `0.30` | Minimum similarity before the pipeline refuses. Provisional until calibrated in T06. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `LOG_DIR` | `logs` | Folder for the rotating log file. Logs also go to stdout. |

### Chat models

The app offers the models in `OPENAI_CHAT_MODELS`; each must appear in the catalogue in
`src/config.py`. All four catalogue models are non-reasoning chat models that accept an explicit
temperature of 0. OpenAI has announced they leave its API on **14 January 2027**.

## Development

```bash
python -m ruff format .      # format
python -m ruff check .       # lint (also enforces type hints and no stray print calls)
python -m pytest             # unit tests; they never call OpenAI
```

To change dependencies, edit `requirements.in` (runtime) or `requirements-dev.in` (tools), then
regenerate the locks with the command at the top of each file. `--universal` keeps the lock
valid on Linux, which Streamlit Community Cloud runs.

## Project layout

```
.env.example            every variable the project reads, with defaults
requirements.in/.txt    runtime dependencies / exact pinned lock (installed by Streamlit Cloud)
requirements-dev.in/.txt  adds pytest and ruff
pyproject.toml          ruff and pytest configuration
src/
  config.py             validated settings; `python -m src.config` smoke check
  utils/api_keys.py     key format checks, masking, redaction, CLI key lookup
  utils/logging_setup.py  console + file logging with key redaction
  ingestion/  retrieval/  chains/   filled in by later tasks
tests/                  pytest suite
docs/CODE_WALKTHROUGH.md  what every file does and why, task by task
```

## Known limitations

- `langchain-community` was archived by its maintainers in June 2026. The FAISS vector store and
  the PDF, CSV and text loaders still live only there, so it is pinned at 0.4.2 and works, but
  it no longer receives fixes.
- The four chat models in the catalogue are scheduled to leave the OpenAI API on 2027-01-14.
