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

---

## Dataset: the Pearlz knowledge base (manual Sec 5)

### What the manual asks for

At least 10 fictional, internally consistent documents (about 9,000-12,000 words, 18-20 pages
or more) in at least three formats, with at least three planted seams, three planted gaps, a
prompt-injection line, and a firmware changelog that changes the meaning of an alert code.

### What was built

| File | Format | Size | Role |
|---|---|---|---|
| `product_manual_aquapearl500.pdf` | PDF | 18 pages | Box contents, specs, controls, lights, filters, cleaning, alert codes E-01 to E-08 |
| `installation_guide_aquapearl.pdf` | PDF | 7 pages | Pre-install checklist, mounting, **first-run flushing** (seam S2), **what voids the warranty** (seam S3) |
| `service_maintenance_agreement.docx` | DOCX | 10 sections | Maintenance plans, response times, **warranty claim procedure** (seam S1), out-of-warranty charges |
| `privacy_policy.docx` | DOCX | 11 sections | Data collected, app telemetry, retention, sharing, rights |
| `warranty_policy.md` | Markdown | 9 sections | Periods, coverage, §3.2 exclusions, discontinued models |
| `refund_returns_policy.md` | Markdown | 9 sections | 14-day window, condition rules, refund times, bundles |
| `shipping_policy.md` | Markdown | 9 sections | Region tiers, cut-offs, fees, next-day cities |
| `troubleshooting_guide.md` | Markdown | 24 symptoms | Symptom tables, "Audible Alert Codes", escalation rules |
| `faq.md` | Markdown | 34 questions | Questions in customer language |
| `customer_service_handbook.md` | Markdown | 8 sections | Internal process; §7 holds the **planted injection line** |
| `firmware_changelog_aquapearl500.txt` | Plain text | 6 versions | 2.4.0 changes the meaning of **E-06** (version conflict) |
| `pricing_guide.csv` | CSV | 25 rows | Every SKU with list and promotional price |

About 15,000 words in 5 formats. `data/knowledge_base/_PLANTED_SEAMS_AND_GAPS.md` is the answer
key: 6 seams, 6 gaps, the injection line, the ambiguities, and a table of canonical facts.

| Supporting file | What it does |
|---|---|
| `data/kb_sources/*.md` | Editable Markdown sources of the two PDFs and the two DOCX files. Never ingested. |
| `scripts/render_kb_documents.py` | Renders those sources to PDF (A5 pages, running header and footer, page numbers) and DOCX (real Word heading styles). |
| `data/knowledge_base/_catalog.json` | Document-level metadata for every file: title, `doc_type`, `product_lines`, `version`, `last_updated`. |

### Design decisions and why

1. **Sources are Markdown; the published files are generated.** Editing a PDF by hand is
   impractical, and the documents are meant to be reviewed and changed. Edit the source, run
   `python -m scripts.render_kb_documents`, and the PDF or DOCX is rebuilt.
2. **The PDFs look like real publications.** Every page has a running header and a footer with
   a page number, which ingestion must detect and strip (Task 02). The manual has page-level
   structure, so citations can say "p. 16".
3. **Unicode fonts in the PDFs.** reportlab's built-in Helvetica has no Unicode map, so text
   extraction turned "38 °C" into "38 ?C" and list bullets into a control character. The
   renderer uses the TrueType fonts bundled with reportlab, and extraction is now clean.
4. **Reproducible PDFs.** `rl_config.invariant = 1` fixes timestamps and IDs, so re-rendering an
   unchanged source gives a byte-identical PDF (verified). The index later uses file hashes to
   decide what changed, so spurious changes would mean spurious re-embedding.
5. **Alert codes use technical vocabulary.** The documents say "triple short tone; FILTER
   indicator pulses red", never "beeps three times". The headline semantic test (T-05) asks
   "my purifier beeps three times and the light flashes red", so it can only succeed by meaning,
   not by shared keywords. An earlier draft did use "beeps three times", which would have made
   the test meaningless; it was caught and rewritten.
6. **An independent consistency review.** A second reviewer checked all 12 documents against
   the canonical-facts table and found 12 issues, all fixed. Examples: two different
   technician response times for the same warranty claim; a cancellation rule that could never
   apply; the FAQ answering a seam question; the manual repeating flush steps that should live
   only in the installation guide; three different escalation points for E-05; and a privacy
   sentence ("products not intended for children") that nearly answered the baby-formula gap.
7. **Fictional names.** Pearlz, AeroPearl, Kestrel Couriers, Lumina Payments and NimbusCloud are
   invented. "AquaPearl" comes from the assignment brief; a similarly named real brand exists
   in India, so the README states that the company is fictional. Emails use the reserved
   `.example` domain; phone numbers and the address are placeholders.

### Viva questions this prepares

- **Q3: Where is semantic search worse than keyword search, in your own KB?** "Our alert codes.
  E-03 is a saturated pre-filter and E-08 is a display fault, but as embeddings 'E-03' and
  'E-08' are nearly identical tokens in nearly identical table rows. Keyword search matches the
  exact code; semantic search can mix them up. The reverse is T-05: 'beeps three times' shares
  no words with 'triple short tone', and only semantic search finds it."
- **Q19: An injected instruction inside a document.** "We planted one on purpose, in
  `customer_service_handbook.md` §7, right next to the compensation limits, because that is
  what refund questions retrieve. It stays in the index so we can prove the prompt-level
  defence works (Task 08)."
- **Q20: The refund policy changes.** "Every document has `version` and `last_updated` in
  `_catalog.json`, and those travel to every chunk. Task 05 shows what the index does with a
  changed file."

---

## T02: Document ingestion

### What the manual asks for

Walk the folder and dispatch each file to a loader by extension (PDF, DOCX or Markdown, text,
CSV); normalise text; strip page headers and footers; attach the metadata contract; keep
loader metadata such as page numbers; skip bad files without stopping; skip duplicates; and
report per file: name, type, characters, pages or sections, and metadata keys.

Acceptance: a folder with one corrupt file loads everything else, logs one warning naming the
bad file, and exits successfully. Every document has a non-empty `source` and `doc_type`.

### Files

| File | What it does |
|---|---|
| `src/ingestion/loaders.py` | `load_knowledge_base(kb_dir)`: the extension-to-loader table `LOADERS`, one loader function per format, the metadata contract, and per-file error handling. Returns an `IngestionResult` (the documents plus one `FileReport` per file). |
| `src/ingestion/text_cleaning.py` | Whitespace and control-character cleanup, running header and footer detection, and splitting text at numbered or capitalised headings. |
| `src/ingestion/report.py` | `python -m src.ingestion.report [--kb-dir PATH]` prints the ingestion report and writes `evaluation/results/ingestion_report.md`. |
| `tests/test_loaders.py` | 17 tests: dispatch, the metadata contract, page metadata kept, header and footer stripping, each format's sections, CSV sentences, and corrupt, encrypted, unsupported, uncatalogued, duplicate, underscore and sub-folder files, plus the real knowledge base. |
| `tests/test_text_cleaning.py` | 11 tests for the cleaning and section-splitting rules. |
| `tests/kb_builders.py` | Writes a small PDF, DOCX, Markdown, text and CSV knowledge base for the tests. |

### Design decisions and why

1. **One Document per structural unit, not per file.** A PDF becomes one Document per section
   on each page; DOCX, Markdown and text files one per heading section; a CSV one per row. So
   every unit already knows its location (`page_number` and `section`, `section`, or `row` and
   `sku`), which is exactly what citations need in Task 10. Chunking (Task 03) splits within
   these units, so a chunk never straddles two sections.
2. **Metadata comes from `_catalog.json`, not from guessing.** `doc_type`, `product_lines`,
   `version` and `last_updated` are written once per file and validated with Pydantic
   (`CatalogEntry`). A file without an entry is skipped with that reason, because a document
   without metadata cannot be filtered or cited properly. `product_lines` is a list because the
   installation and troubleshooting guides cover several product lines.
3. **Loader metadata is kept, not overwritten.** PyPDFLoader's `page` (counted from 0) stays as
   it is, and `page_number` (counted from 1, for people) is added beside it. The loader's full
   path moves to `file_path`, and `source` becomes the file name the contract asks for.
4. **Running headers and footers are detected, not hard-coded.** A line counts as a running
   line if, ignoring digits ("Page 7" equals "Page 8"), it appears among the first or last three
   lines of at least 60% of a PDF's pages and contains at least three letters. Searching only
   the page edges means a table heading or "Step 1" that recurs mid-page is never removed; the
   letter rule means bare list numbers are never removed. The report lists what was stripped,
   as the manual asks.
5. **A PDF heading's number must contain a dot.** "13. Audible alert codes" and "11.2
   Replacing..." are headings; "50 Hz. Do not use..." (a wrapped line) and "48 W; standby" (a
   table cell) are not. The first version of the rule matched both false positives; they were
   found by listing every match in the real manual.
6. **A custom DOCX loader.** LangChain's `Docx2txtLoader` flattens the file and loses the
   headings, so it cannot say which section a sentence came from. `DocxSectionLoader` is a
   LangChain `BaseLoader` that walks paragraphs and tables in order and starts a new Document at
   each Word heading. Tables become "cell | cell" rows.
7. **Pricing rows become self-describing sentences** (manual mistake #13): "Sediment
   pre-filter PF-1 (SKU F5-PF1), replacement filter for the AquaPearl 500 Pro. ... List price:
   PKR 2,400. Current promotional price: PKR 1,990." A price can never be separated from the
   product it belongs to.
8. **One bad file never stops the run.** The loader call is wrapped in a broad `except`,
   because third-party parsers raise many different exception types for bad files.
   `_skip_reason` turns the common ones into plain reasons ("password-protected PDF",
   "corrupt DOCX").
9. **Duplicates are skipped by content hash**, so a copied file is reported as "duplicate of
   policy.md" instead of doubling its chunks.
10. **Files whose names start with `_` or `.` are never loaded.** The answer key of planted gaps
    lives in such a file; if it were ingested, the "unanswerable" questions would be answered
    from it.
11. **pypdf's own warnings are muted to errors.** For a corrupt file, pypdf logs "EOF marker not
    found" before our loader logs its warning; the manual asks for one clear warning naming the
    file.

### Evidence (real output)

```text
$ python -m src.ingestion.report --kb-dir <copy of the knowledge base plus a corrupt PDF>
WARNING | src.ingestion.loaders | Skipping warranty_scan_2025.pdf: unreadable or corrupt PDF (Stream has ended unexpectedly)
INFO    | src.ingestion.loaders | Ingestion finished: 13 files found, 12 loaded, 1 skipped
(exit code 0)

$ python -m src.ingestion.report
Files found: 12, loaded: 12, skipped: 0. Documents (structural units) produced: 220.
Stripped from the manual: "AquaPearl # Pro User Manual | Revision C | Firmware #.#", "Page #",
"Pearlz Home Systems (Pvt.) Ltd. | pearlzhome.example"
```

The full per-file table is in `evaluation/results/ingestion_report.md`. `pytest`: 73 passed.

### Viva questions this prepares

- **Mistake #2 (metadata lost during splitting):** "Our loaders attach the contract to every
  unit before any splitting happens, and `test_every_document_carries_the_metadata_contract`
  checks every document. Task 03 checks it again after splitting."
- **Mistake #13 (tabular data ingested as prose):** "Each pricing row is one Document and one
  sentence that names the SKU and the product next to the price."
- **Q19, the ingestion-time defence:** "Ingestion is where a real system would scan for
  instruction-like text. We deliberately do not strip the planted line, so we can show that the
  prompt-level defence holds. In production we would flag such lines for human review at
  ingestion."

---

## T03: Chunking strategy

### What the manual asks for

A recursive character splitter as the baseline; at least three sizes and two overlaps; at least
one structure-aware alternative; for each configuration the chunk count, mean and maximum
length and hit@4 on five sample questions; proof that metadata survives splitting; and a
justification that uses our own numbers.

### Files

| File | What it does |
|---|---|
| `src/ingestion/chunking.py` | `split_into_chunks` (RecursiveCharacterTextSplitter inside each structural unit, stable chunk ids such as `warranty_policy.md::0007`), `add_context_headers`, `build_chunks` (the production recipe from settings), `assert_within_embedding_limit`, `chunk_statistics`. |
| `evaluation/retrieval_questions.json` | 10 retrieval questions with accepted source documents and answer patterns. R01-R05 are the five chunking samples. Written before any tuning. |
| `evaluation/retrieval_checks.py` | `contains_answer` (right source and every pattern matches) and `first_hit_rank`. No LLM involved. |
| `evaluation/experiments/chunking.py` | `python -m evaluation.experiments.chunking`: runs 12 configurations and writes `evaluation/results/chunking_experiment.md`. |
| `evaluation/experiments/common.py` | Shared setup for experiment scripts: settings, logging, API key, result files, Markdown tables. |
| `tests/test_chunking.py` | 10 tests: metadata survives splitting, ids unique and stable, overlap shared, short units kept whole, context headers, over-long chunks refused, production chunks of the real knowledge base. |

### The experiment (real run, 2026-10-26)

Twelve configurations, each embedded with `text-embedding-3-small` and searched by cosine
similarity, top 4. "Sample" is the manual's five questions; MRR is the mean of 1/rank of the
first chunk containing the answer over all ten questions (0 when it is not in the top 4).

| Strategy | Size / overlap | Chunks | Mean chars | hit@4 sample | hit@4 all 10 | MRR |
|---|---|---|---|---|---|---|
| format-blind | 300 / 0 | 397 | 220 | 5/5 | 8/10 | 0.51 |
| format-blind | 300 / 45 | 409 | 224 | 5/5 | 8/10 | 0.58 |
| format-blind | 800 / 0 | 130 | 676 | 4/5 | 8/10 | 0.62 |
| format-blind | 800 / 120 | 138 | 684 | 4/5 | 8/10 | 0.61 |
| format-blind | 1500 / 0 | 70 | 1256 | 4/5 | 8/10 | 0.50 |
| format-blind | 1500 / 225 | 76 | 1274 | 5/5 | 9/10 | 0.68 |
| structure-aware | 300 / 45 | 435 | 204 | 4/5 | 7/10 | 0.53 |
| structure-aware | 800 / 120 | 246 | 357 | 4/5 | 7/10 | 0.65 |
| structure-aware | 1500 / 225 | 226 | 387 | 5/5 | 8/10 | 0.68 |
| structure-aware + header | 300 / 45 | 435 | 263 | 4/5 | 8/10 | 0.61 |
| structure-aware + header | 800 / 120 | 246 | 416 | 5/5 | 9/10 | 0.68 |
| **structure-aware + header** | **1500 / 225** | **226** | **446** | **5/5** | **9/10** | **0.72** |

**Adopted:** structure-aware splitting with context headers, `CHUNK_SIZE=1500`,
`CHUNK_OVERLAP=225` (15%), `CHUNK_CONTEXT_HEADERS=true`.

### Why this configuration (the justification, with our numbers)

- **It ties for the best hit@4** (5/5 on the samples, 9/10 overall) and has **the best MRR,
  0.72**, so the answer is usually the first chunk, not just somewhere in the top 4.
- **The format-blind 1500/225 baseline also reaches 9/10**, but its chunks have no page or
  section; they span several sections of a file, so a citation could only say "somewhere in
  the manual". Structure-aware chunks carry `page_number` and `section` for Task 10.
- **The size limit only matters for long sections.** Structure-aware chunks average 387-446
  characters because most sections are short; 1500 decides how long tables (the
  troubleshooting symptoms, the alert codes) are cut.
- **The trade-off, seen in our data.** Small chunks are precise but strip context: at
  structure-aware 300 the cleaning question (R04) was missed, because the cleaning-schedule
  table was cut away from the heading that says what it is. Large format-blind chunks keep
  context by merging sections: format-blind 1500 is the only setting that found the privacy
  telemetry chunk (R08, rank 2), because that chunk merged the whole "data collected through
  the app" part. But merged chunks average everything they contain into one vector and cannot
  be cited precisely.
- **Overlap.** At 300 characters, overlap 45 raised MRR from 0.51 to 0.58 (R02 moved from rank
  3 to 1: the alert-code row had been cut at a boundary). At 1500, overlap 225 found R05, which
  0% missed. At 800 it made no difference. 15% is the setting that never hurt.

### How the context header was found (debugging discipline)

The first run, without headers, missed R05, R08 and R10 at structure-aware 1500. Following the
manual's order (check retrieval before touching prompts), the top-6 chunks were inspected:

- **R05** was actually found, at ranks 3 and 4. The troubleshooting symptoms table outranks
  the installation guide, which is the seam working as designed.
- **R08** missed because the DOCX section "3.2 Water-usage and device telemetry" loses its
  parent heading "3. Data we collect through the Pearlz Home app", so the chunk never says
  "app".
- **R10** (E-06) missed because the old E-06 rows in the manual and troubleshooting guide
  outrank the changelog: retrieval prefers the outdated meaning.

The hypothesis was that a "Document > section path" header line would fix R08. **Measured
result: it did not fix R08** (still outside the top 4), **but it fixed R10** (changelog now
rank 2) and raised MRR from 0.68 to 0.72. R08 stays a known retrieval miss, revisited with
larger k and MMR in Task 06. This is reported as found, not as hoped.

### Design decisions and why

1. **Split inside structural units, never across them.** A chunk never mixes the end of one
   section with the start of the next, so its embedding is about one thing and its citation
   names one place.
2. **Readable chunk ids** (`source::0007`) appear in logs and the "Behind the answer" panel, so
   a retrieval trace reads like a list of places.
3. **Headers are added after splitting**, so every piece of a long section, not only the first,
   knows which section it belongs to. The header is also stored in `metadata["context_header"]`
   so citation snippets can leave it out.
4. **Pricing rows stay whole.** At the production size every row is one chunk; the test
   `test_production_chunks_of_the_real_knowledge_base_keep_their_metadata` checks there is
   exactly one chunk per SKU, so a price is never split from its product (manual mistake #13).

### Viva questions this prepares

- **Q1: Why chunk at all?** "Whole documents do not fit the context budget, and one vector for
  an 18-page manual averages every topic into a point that is close to nothing in particular.
  Our format-blind runs show the milder version of this: at 1500 characters with 0% overlap,
  MRR fell to 0.50. Chunks also make citations possible: page 16, section 13."
- **Q5: What is overlap for, and what goes wrong at 0% and at 60%?** "At 0% an answer that
  straddles a boundary is cut in two. At 300 characters, 15% overlap moved the E-03 row from
  rank 3 to rank 1. At 60% the index grows by more than half again and near-duplicate chunks
  crowd the top 4, so fewer distinct passages reach the model. We use 15%."
- **Q7 (k) and Q11 (retrieval without the LLM)** start here: every number above comes from
  retrieval alone, scored against answer patterns written before tuning.

---

## T04: Embeddings

### What the manual asks for

Choose an embedding model and record its name, dimension and input limit; check chunk size
against that limit; embed in batches with retry and backoff; log time and tokens; make runs
resumable or cached; run a three-sentence similarity diagnostic; and explain the vector,
cosine similarity, and what breaks if documents and queries use different models.

### Files

| File | What it does |
|---|---|
| `src/llm/clients.py` | `build_embeddings(api_key, settings)` and `build_chat_model(...)`: the only place OpenAI objects are created, always from an explicit key (never from the environment), never cached. |
| `src/ingestion/embedding_cache.py` | `build_cached_embedder`: LangChain's `CacheBackedEmbeddings` over `SQLiteByteStore` (one SQLite file), wrapping `TokenCountingEmbeddings`, which logs every batch with its size, tokens and time. |
| `src/retrieval/vector_store.py` | `create_vector_store` (FAISS, inner product) and `assert_unit_length`. |
| `evaluation/experiments/embedding_diagnostic.py` | `python -m evaluation.experiments.embedding_diagnostic`: writes `evaluation/results/embedding_diagnostic.md`. |
| `tests/test_embedding_cache.py` | 5 tests with a fake model: store round trip, no text embedded twice, **a crash mid-run keeps finished batches**, another model never reuses vectors, token counting. |

### Measured (real run, 2026-10-26)

| Property | Value |
|---|---|
| Model | `text-embedding-3-small` |
| Dimension | 1536 (measured and documented) |
| Vector length | 0.9998 to 1.0002 (unit length, measured) |
| Maximum input | 8,192 tokens documented; LangChain splits above 8,191 |
| Longest production chunk | 446 tokens (1,551 characters including its header) |
| Paraphrases, customer vs manual wording | cosine **0.627** |
| Each paraphrase vs an unrelated sentence | **0.054** and **0.024** |
| "Alert E-03 is shown" vs "Alert E-08 is shown" | **0.869** |
| Embedding cost of both chunking runs | 1,970 texts, 196,152 tokens, about US$0.004 at $0.02 per million tokens |

### Design decisions and why

1. **Cache first, then OpenAI, one batch at a time.** `CacheBackedEmbeddings` looks every text
   up by `sha256(text)` under the model's name and sends only the misses, in batches of
   `EMBEDDING_BATCH_SIZE` (64). Each batch is stored before the next starts. The test
   `test_a_crash_mid_run_keeps_the_finished_batches` makes the third call fail; on the rerun
   only the 2 remaining texts are embedded.
2. **One SQLite file, not one file per vector.** LangChain's `LocalFileStore` would write about
   2,000 small files, all of which OneDrive would try to sync. `SQLiteByteStore` is a 40-line
   LangChain `ByteStore`.
3. **Retry and backoff come from the OpenAI client** (`OPENAI_MAX_RETRIES=4`, exponential backoff
   on timeouts, 429s and 5xx), configured in `build_embeddings`.
4. **The cache key includes the model name**, so switching `OPENAI_EMBEDDING_MODEL` can never
   mix vectors from two models (tested).
5. **Chunks are checked against the input limit before embedding.** `OpenAIEmbeddings` would
   silently split an over-long text and average the pieces; `assert_within_embedding_limit`
   refuses such a chunk instead (manual mistake #11). Ours peak at 446 tokens.
6. **Inner product equals cosine here.** The vectors are unit length (measured), and for unit
   vectors the inner product is the cosine. The first version also passed `normalize_L2=True`;
   LangChain warned that this "is not applicable" to inner product (it still normalised). The
   flag was removed, and `assert_unit_length` now verifies the property on the built index.
7. **Keys stay out of shared objects.** `build_embeddings` requires the key as an argument and
   is called per session; the cache holds only hashes and vectors, so it is safe to share.

### Viva questions this prepares

- **Q2: What does an embedding represent?** "A position in a 1536-dimensional space learned
  from how text is used, where closeness means similar meaning; the individual dimensions are
  not human-readable features. 'My purifier keeps beeping three times' and 'the unit sounds a
  triple short tone' share almost no words, yet score 0.627, against 0.054 for an unrelated
  sentence."
- **Why cosine, not Euclidean?** "Cosine compares direction and ignores length, and direction is
  what carries meaning. Our vectors are unit length, so cosine, inner product and Euclidean
  distance give the same ranking. We use inner product, which for unit vectors is the cosine."
- **Q4: Different models for documents and queries.** "Each model has its own space; even
  with equal dimensions the axes mean different things. Retrieval would turn near-random with
  no error at all. That is why our cache keys and (Task 05) the index manifest record the model
  name, and loading refuses a mismatch."
- **Q3 (again):** "E-03 against E-08 scores 0.869 although they mean different things: exact
  codes are where keyword search wins."
