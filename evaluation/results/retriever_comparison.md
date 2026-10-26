# Retriever comparison (Task 06)

Run: 2026-10-26 08:57 UTC. Embedding model: `text-embedding-3-small`. Index: chunk size 1500, overlap 225, context headers True. Threshold filter uses RELEVANCE_THRESHOLD = 0.34. No LLM involved.

| Strategy | hit@k (10 questions) | MRR | Distinct documents returned | Chunks handed on | Mean latency (ms, incl. query embedding) |
|---|---|---|---|---|---|
| similarity, k=3 | **9/10** | 0.72 | 1.9 | 3.0 | 358 |
| similarity, k=4 | **9/10** | 0.72 | 2.0 | 4.0 | 350 |
| similarity, k=8 | **9/10** | 0.72 | 2.6 | 8.0 | 333 |
| MMR, k=4 | **6/10** | 0.60 | 2.9 | 4.0 | 331 |
| MMR, k=8 | **8/10** | 0.63 | 3.9 | 8.0 | 364 |
| similarity, k=8, threshold filter | **9/10** | 0.72 | 2.6 | 8.0 | 322 |
| similarity, k=4, doc_type filter (oracle) | **9/10** | 0.78 | 1.2 | 3.7 | 344 |

## Rank of the first chunk containing the answer ("-" = not returned)

| Strategy | R01 | R02 | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 |
|---|---|---|---|---|---|---|---|---|---|---|
| similarity, k=3 | 1 | 1 | 1 | 1 | 3 | 1 | 1 | - | 3 | 2 |
| similarity, k=4 | 1 | 1 | 1 | 1 | 3 | 1 | 1 | - | 3 | 2 |
| similarity, k=8 | 1 | 1 | 1 | 1 | 3 | 1 | 1 | - | 3 | 2 |
| MMR, k=4 | 1 | 1 | 1 | 1 | - | 1 | 1 | - | - | - |
| MMR, k=8 | 1 | 1 | 1 | 1 | 5 | 1 | 1 | - | 7 | - |
| similarity, k=8, threshold filter | 1 | 1 | 1 | 1 | 3 | 1 | 1 | - | 3 | 2 |
| similarity, k=4, doc_type filter (oracle) | 1 | 1 | 1 | 1 | 2 | 1 | 1 | - | 3 | 1 |

- **R01**: How long is the warranty on the AquaPearl 500 Pro?
- **R02**: My purifier beeps three times and the light flashes red. What should I do?
- **R03**: How much does a replacement sediment filter cost?
- **R04**: How do I clean the unit?
- **R05**: Water tastes weird after I changed the filter.
- **R06**: What's the return window?
- **R07**: How long does delivery take to Skardu?
- **R08**: What's your privacy policy on app data?
- **R09**: My unit leaked. How do I make a warranty claim and how long does it take?
- **R10**: What does error E-06 mean on my AquaPearl?
