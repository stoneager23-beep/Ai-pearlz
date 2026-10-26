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
| T06 | Retriever comparison and relevance gate | Done |
| T07 | The RAG chain | Done |
| T08 | Prompt engineering for grounding | Done |
| T09 | Conversational memory and follow-ups | Done |
| T10 | Source attribution | Done |
| T11 | Evaluation | Done |
| — | Streamlit web app | Done (deploying it is a manual step, below) |

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

## Chatting on the command line

```bash
python -m src.app_cli                          # default model (gpt-4.1-mini)
python -m src.app_cli --model gpt-4o           # another offered model
python -m src.app_cli --product "AquaPearl 300" --doc-type policy   # restrict retrieval
```

Each answer shows its sources (document, page or section, and a short verbatim snippet), a
confidence of high, partial or none, and, for follow-up questions, the standalone question that
was actually searched. Commands: `/reset` starts a new conversation, `/model gpt-4o` switches
model, `/verbose` shows what happened behind each answer (retrieved chunks with scores, gate
decision, tokens, latency), `/quit` leaves. Every turn is logged as one JSON line in
`logs/supportpearlz.log`.

## The web app

```bash
# from the project's virtual environment (see Setup), not the system Python
python -m streamlit run streamlit_app.py      # then open http://localhost:8501
```

Start it from the activated virtual environment. A bare `streamlit run` can pick up another
Python on your PATH that lacks the project's packages; the page then says which package is
missing.

1. **Key gate.** The first screen asks for your own OpenAI API key, locally and when deployed.
   The key is checked offline for its format, then with one tiny embedding request. Each failure
   has its own message: malformed, rejected (401), no credit, rate-limited, timeout, outage. The
   key is kept in memory for that browser session only. "Change or remove key" in the sidebar
   forgets it.
2. **First use on a fresh server.** If no index has been built yet, the app builds it once with
   the visitor's key and says roughly what that costs (12 documents, 226 chunks, about 24,900
   tokens of embeddings). Concurrent visitors wait on a file lock instead of building twice.
3. **Ready screen.** Example questions (each one a case from the evaluation set) and a chat box.
4. **Answers** stream in as they are written. When complete they show numbered references,
   source cards with the exact snippet, a confidence chip, tokens and time. "Behind the answer"
   shows the rewritten question, the gate decision, every retrieved chunk with its score, the
   model and the prompt version.
5. **Sidebar.** New conversation, model picker (only models your key can use), filters by
   document type and product, knowledge-base facts, how it works, your key and the tokens used.

Multi-user safety: `st.cache_resource` holds only the key-free index data. Each visitor's chat
model and query embeddings are built from the key in their own session and are never cached
(`tests/test_session_isolation.py` proves two sessions share no client).

### Deploying to Streamlit Community Cloud

1. Push the repository to GitHub. `.env`, `.streamlit/secrets.toml`, `data/vector_store/` and
   the manual PDF are git-ignored. Check with `git status` that none of them is staged.
2. On share.streamlit.io choose **Create app**, pick the repository and branch, and set the main
   file to `streamlit_app.py`.
3. Under **Advanced settings** choose **Python 3.11**. Leave **Secrets** empty, or paste only
   the optional settings from `.streamlit/secrets.toml.example`. **Never add an OpenAI key.**
4. Deploy. The first visitor's validated key builds the index once (about 25,000 embedding
   tokens). It lasts until the app restarts or is redeployed.
5. To change the knowledge base, edit `data/knowledge_base/`, commit and push. On the first
   question after the restart the index is rebuilt, and only changed chunks are embedded again.

## Evaluation and experiments

```bash
python -m evaluation.run_eval                     # the 26-case test set; writes eval_results.md/.json
python -m evaluation.run_eval --cases T-07,T-08   # a subset
python -m evaluation.run_eval --rescore           # re-apply the rubric to saved answers (no API calls)
python -m evaluation.experiments.chunking         # Task 03: 12 chunking configurations
python -m evaluation.experiments.embedding_diagnostic   # Task 04
python -m evaluation.experiments.retrievers       # Task 06: 7 retrieval strategies
python -m evaluation.experiments.threshold        # Task 06: relevance-gate calibration
python -m evaluation.experiments.prompts          # Task 08: weak versus grounded prompt
python -m evaluation.experiments.conversation     # Task 09: follow-ups and a topic switch
python -m evaluation.experiments.citations        # Task 10: citations checked against the sources
```

All results are written to `evaluation/results/`. The human review of the evaluation, with the
failure analysis, is `evaluation/results/eval_review.md`. A full evaluation run costs about
51,000 input tokens for the system plus the judge's calls.

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
| `RETRIEVAL_SEARCH_TYPE` | `similarity` | `similarity` or `mmr`. Similarity won the T06 comparison. |
| `RETRIEVAL_K` | `4` | Chunks retrieved per question. Chosen in T06. |
| `RETRIEVAL_FETCH_K` | `20` | Candidates considered before MMR or metadata filtering. |
| `RETRIEVAL_MMR_LAMBDA` | `0.5` | MMR balance between relevance (1.0) and diversity (0.0). |
| `RELEVANCE_THRESHOLD` | `0.34` | Minimum cosine similarity of the best chunk; below it the question is refused without calling the model. Calibrated in T06. |
| `CONFIDENCE_HIGH_SCORE` | `0.50` | Below this best-chunk similarity, a "high" confidence becomes "partial". |
| `MAX_CONTEXT_CHARACTERS` | `8000` | Most retrieved text put into one prompt; drops are logged. |
| `HISTORY_TURNS` | `4` | Earlier turns used to rewrite follow-up questions. |
| `ANSWER_PROMPT_VERSION` | `v2` | `v1` is the weak baseline kept for the T08 comparison. |
| `CONDENSE_PROMPT_VERSION` | `c2` | Follow-up rewrite prompt version. |
| `SUPPORT_CONTACT` | email, toll-free, WhatsApp | Human contact given in refusals; must match the documents. |
| `EVAL_JUDGE_MODEL` | `gpt-4.1` | Model that judges groundedness in the evaluation. |
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
  retrieval/retriever.py  scored retriever (similarity or MMR, metadata filters) and relevance gate
  llm/clients.py        the only place OpenAI objects are created (always from an explicit key)
  chains/schemas.py     AnswerDraft (model output) and SupportResponse (what every interface gets)
  chains/context.py     labelled [S1]..[Sk] context blocks within a character budget
  chains/prompts.py     versioned answer (v1, v2) and rewrite (c1, c2) prompts
  chains/memory.py      bounded history and follow-up rewriting
  chains/citations.py   citation validation, de-duplication and snippets
  chains/rag_chain.py   the composed LCEL chain
  chains/session.py     one conversation: memory, error handling, per-turn logging
  chains/streaming.py   streams the answer text out of the model's JSON (web app)
  llm/key_check.py      validates a pasted key: format, one tiny request, usable models
  retrieval/shared_index.py  the key-free part of the index that web sessions share
  app_cli.py            `python -m src.app_cli`
  errors.py             every failure to one short, human message
evaluation/
  retrieval_questions.json  retrieval ground truth for the chunking and retriever experiments
  test_questions.json   the frozen 26-case evaluation set
  run_eval.py           the evaluation harness; scoring.py is the rubric, judge.py the groundedness judge
  experiments/          runnable experiments (chunking, embeddings, retrievers, threshold, prompts, ...)
  results/              generated reports and experiment tables
streamlit_app.py        web app entry point (thin; Community Cloud runs it)
.streamlit/             config.toml (theme, error details off) and secrets.toml.example
app/
  main.py               one page run: gate, index, the visitor's session, page
  state.py              everything kept in st.session_state (the only place the key lives)
  services.py           the shared key-free index (st.cache_resource) and per-visitor sessions
  ui/theme.py           design tokens; assets/styles.css is the stylesheet built on them
  ui/gate.py            the key screen
  ui/conversation.py    ready screen, past turns, streaming a new answer
  ui/sidebar.py         controls, filters, knowledge-base facts, key and cost
  ui/components.py      answer, source cards, confidence chip, "Behind the answer" (all escaped)
  ui/scene3d.py         the 3D pearl component (assets/pearl_scene/index.html, three.js 0.185.0)
tests/                  pytest suite (never calls OpenAI)
docs/CODE_WALKTHROUGH.md  what every file does and why, task by task
```

## Known limitations

- `langchain-community` was archived by its maintainers in June 2026. The FAISS vector store and
  the PDF, CSV and text loaders still live only there, so it is pinned at 0.4.2 and works, but
  it no longer receives fixes.
- The four chat models in the catalogue are scheduled to leave the OpenAI API on 2027-01-14.
- Multi-part policy questions whose deciding clause sits inside a long numbered list can miss it:
  the list is one chunk (T-08 in the evaluation). See `evaluation/results/eval_review.md`.
- Temperature 0 makes answers nearly, not perfectly, repeatable across runs.
