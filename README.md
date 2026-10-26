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
| — | Knowledge base (12 documents) | Done |
| T02 | Document ingestion | Done |
| T03 | Chunking strategy | Done |
| T04 | Embeddings | Done |
| T05 | Vector store | Done |
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

## The knowledge base

`data/knowledge_base/` holds 12 documents for the fictional company Pearlz Home Systems, in five
formats: two PDFs (the AquaPearl 500 Pro manual and the installation guide), two DOCX files
(service agreement, privacy policy), six Markdown files (warranty, refunds, shipping,
troubleshooting, FAQ, support handbook), a plain-text firmware changelog and a CSV price list.
About 15,000 words in total.

> **Pearlz Home Systems and all of its products, partners, policies, phone numbers and
> addresses are fictional**, written for this assignment. Email addresses use the reserved
> `.example` domain.

- `_catalog.json` gives every document its `doc_type`, product lines, version and date.
- `_PLANTED_SEAMS_AND_GAPS.md` is the answer key of deliberately planted cross-document facts,
  unanswerable questions and a prompt-injection line. Files starting with `_` are never
  ingested.
- The PDF and DOCX files are generated from editable Markdown in `data/kb_sources/`. After
  editing a source, run `python -m scripts.render_kb_documents` (needs `requirements-dev.txt`).

### Checking ingestion

```bash
python -m src.ingestion.report
```

Loads every document without calling OpenAI and prints a per-file report (type, characters,
pages, structural units, metadata keys, and any running headers or footers stripped). The
report is also saved to `evaluation/results/ingestion_report.md`. Unreadable files are skipped
with a warning; the rest still load.

## Building the index

```bash
python -m src.ingestion.build_index            # build if missing, otherwise update what changed
python -m src.ingestion.build_index --rebuild  # rebuild everything from scratch
python -m src.retrieval.search "how long is the warranty" --k 5   # inspect retrieval
```

The build loads the knowledge base, splits it into chunks, embeds them with
`text-embedding-3-small` and saves a FAISS index to `data/vector_store/` (git-ignored), with a
manifest of what built it. Running it again only processes files that changed: their old
chunks are deleted and replaced. Embeddings are cached in `data/embedding_cache/`, so text that
was embedded before is never paid for twice. A full build of this knowledge base embeds about
25,000 tokens (well under one US cent at OpenAI's published price).

The chat and the web app load the saved index at start-up and build it only if it is missing
or out of date. An index built with a different embedding model or different chunk settings
is never used; it is rebuilt.

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
| `OPENAI_TIMEOUT_SECONDS` | `30` | Seconds before an OpenAI request is abandoned. |
| `OPENAI_MAX_RETRIES` | `4` | Retries with exponential backoff after a timeout, rate limit or server error. |
| `EMBEDDING_BATCH_SIZE` | `64` | Chunks per embedding request; each finished batch is cached. |
| `KNOWLEDGE_BASE_DIR` | `data/knowledge_base` | Folder of source documents. |
| `VECTOR_STORE_DIR` | `data/vector_store` | Where the index is saved (git-ignored). |
| `COLLECTION_NAME` | `pearlz_kb` | Name of the index inside `VECTOR_STORE_DIR`. |
| `EMBEDDING_CACHE_PATH` | `data/embedding_cache/embeddings.sqlite3` | Cache of computed embeddings (git-ignored). |
| `RESULTS_DIR` | `evaluation/results` | Where experiment and evaluation scripts write their tables. |
| `CHUNK_SIZE` | `1500` | Maximum characters per chunk; shorter sections stay whole. Chosen by the T03 experiment. |
| `CHUNK_OVERLAP` | `225` | Characters shared by neighbouring chunks of a long section (15%). |
| `CHUNK_CONTEXT_HEADERS` | `true` | Start each chunk with "Document > section path". |
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
data/
  knowledge_base/       the 12 source documents, _catalog.json, planted-gaps answer key
  kb_sources/           editable Markdown sources of the PDF and DOCX documents
scripts/
  render_kb_documents.py  rebuilds the PDF and DOCX documents from kb_sources
src/
  config.py             validated settings; `python -m src.config` smoke check
  utils/api_keys.py     key format checks, masking, redaction, CLI key lookup
  utils/logging_setup.py  console + file logging with key redaction
  ingestion/loaders.py  file-type dispatch, metadata contract, per-file error handling
  ingestion/text_cleaning.py  whitespace, running headers/footers, section splitting
  ingestion/report.py   `python -m src.ingestion.report`
  ingestion/chunking.py  splitting inside sections, context headers, length checks
  ingestion/embedding_cache.py  cached, batched, token-counted embeddings
  ingestion/indexing.py  full build, incremental update, load_or_build
  ingestion/build_index.py  `python -m src.ingestion.build_index`
  retrieval/vector_store.py  FAISS save/load with a manifest
  retrieval/search.py   `python -m src.retrieval.search`
  llm/clients.py        the only place OpenAI objects are created (always from an explicit key)
  errors.py             every failure to one short, human message
  chains/               filled in by later tasks
evaluation/
  retrieval_questions.json  retrieval ground truth for the chunking and retriever experiments
  experiments/          runnable experiments (chunking, embedding diagnostic, ...)
  results/              generated reports and experiment tables
tests/                  pytest suite (never calls OpenAI)
docs/CODE_WALKTHROUGH.md  what every file does and why, task by task
```

## Known limitations

- `langchain-community` was archived by its maintainers in June 2026. The FAISS vector store and
  the PDF, CSV and text loaders still live only there, so it is pinned at 0.4.2 and works, but
  it no longer receives fixes.
- The four chat models in the catalogue are scheduled to leave the OpenAI API on 2027-01-14.
