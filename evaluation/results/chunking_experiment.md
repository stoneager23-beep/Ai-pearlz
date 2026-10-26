# Chunking experiment (Task 03)

Run: 2026-10-26 08:40 UTC. Embedding model: `text-embedding-3-small`. Retrieval: cosine similarity, top 4. No LLM involved.

## Results

| Strategy | Size (chars) | Overlap | Chunks | Mean chars | Max chars | Max tokens | hit@4, 5 sample questions | hit@4, all 10 questions | MRR, all 10 questions |
|---|---|---|---|---|---|---|---|---|---|
| recursive, format-blind | 300 | 0 (0%) | 397 | 220 | 300 | 98 | **5/5** | 8/10 | 0.51 |
| recursive, format-blind | 300 | 45 (15%) | 409 | 224 | 300 | 101 | **5/5** | 8/10 | 0.58 |
| recursive, format-blind | 800 | 0 (0%) | 130 | 676 | 799 | 247 | **4/5** | 8/10 | 0.62 |
| recursive, format-blind | 800 | 120 (15%) | 138 | 684 | 799 | 248 | **4/5** | 8/10 | 0.61 |
| recursive, format-blind | 1500 | 0 (0%) | 70 | 1256 | 1499 | 446 | **4/5** | 8/10 | 0.50 |
| recursive, format-blind | 1500 | 225 (15%) | 76 | 1274 | 1498 | 456 | **5/5** | 9/10 | 0.68 |
| structure-aware | 300 | 45 (15%) | 435 | 204 | 300 | 98 | **4/5** | 7/10 | 0.53 |
| structure-aware | 800 | 120 (15%) | 246 | 357 | 800 | 238 | **4/5** | 7/10 | 0.65 |
| structure-aware | 1500 | 225 (15%) | 226 | 387 | 1495 | 428 | **5/5** | 8/10 | 0.68 |
| structure-aware + context header | 300 | 45 (15%) | 435 | 263 | 395 | 117 | **4/5** | 8/10 | 0.61 |
| structure-aware + context header | 800 | 120 (15%) | 246 | 416 | 879 | 256 | **5/5** | 9/10 | 0.68 |
| structure-aware + context header | 1500 | 225 (15%) | 226 | 446 | 1551 | 446 | **5/5** | 9/10 | 0.72 |

## Rank of the first chunk containing the answer ("-" = not in the top 4)

| Configuration | R01 | R02 | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 |
|---|---|---|---|---|---|---|---|---|---|---|
| recursive, format-blind 300/0 | 1 | 3 | 1 | 2 | 4 | 2 | 1 | - | - | 2 |
| recursive, format-blind 300/45 | 1 | 1 | 1 | 4 | 4 | 1 | 1 | - | - | 3 |
| recursive, format-blind 800/0 | 1 | 1 | 3 | 1 | - | 1 | 1 | - | 3 | 2 |
| recursive, format-blind 800/120 | 1 | 1 | 4 | 1 | - | 1 | 1 | - | 2 | 3 |
| recursive, format-blind 1500/0 | 1 | 1 | 2 | 2 | - | 2 | 2 | 2 | 2 | - |
| recursive, format-blind 1500/225 | 1 | 1 | 2 | 2 | 4 | 1 | 1 | 2 | 1 | - |
| structure-aware 300/45 | 1 | 2 | 1 | - | 4 | 1 | 1 | - | - | 2 |
| structure-aware 800/120 | 1 | 1 | 1 | 1 | - | 1 | 1 | - | 2 | - |
| structure-aware 1500/225 | 1 | 1 | 1 | 1 | 3 | 1 | 1 | - | 2 | - |
| structure-aware + context header 300/45 | 1 | 1 | 1 | 2 | - | 1 | 1 | - | 4 | 3 |
| structure-aware + context header 800/120 | 1 | 1 | 1 | 1 | 4 | 1 | 1 | - | 3 | 4 |
| structure-aware + context header 1500/225 | 1 | 1 | 1 | 1 | 3 | 1 | 1 | - | 3 | 2 |

## Questions

- **R01** (sample): How long is the warranty on the AquaPearl 500 Pro?
- **R02** (sample): My purifier beeps three times and the light flashes red. What should I do?
- **R03** (sample): How much does a replacement sediment filter cost?
- **R04** (sample): How do I clean the unit?
- **R05** (sample): Water tastes weird after I changed the filter.
- **R06**: What's the return window?
- **R07**: How long does delivery take to Skardu?
- **R08**: What's your privacy policy on app data?
- **R09**: My unit leaked. How do I make a warranty claim and how long does it take?
- **R10**: What does error E-06 mean on my AquaPearl?

A chunk contains the answer when it comes from an accepted source document and matches every answer pattern in `evaluation/retrieval_questions.json`.

Embedding cost of this run: 590 texts and 52,302 tokens sent to OpenAI (cache hits are free and not counted).
