# Embedding diagnostic (Task 04)

Run: 2026-10-26 08:43 UTC.

## The model

| Property | Value |
|---|---|
| Model | `text-embedding-3-small` |
| Vector dimension (measured) | 1536 |
| Vector dimension (documented) | 1536 |
| Vector length, min to max (measured) | 0.9998 to 1.0002 |
| Maximum input (documented) | 8,192 tokens |
| LangChain splits inputs longer than | 8,191 tokens |
| Longest production chunk | 446 tokens (1551 characters), chunk size 1500 |

## Paraphrases versus an unrelated sentence

- **A (customer words)**: My purifier keeps beeping three times and the light is flashing red.
- **B (manual words)**: The unit sounds a triple short tone and its FILTER indicator pulses red.
- **C (unrelated)**: Next-day delivery is offered in Karachi, Lahore and Islamabad.

| Pair | Cosine similarity |
|---|---|
| A (customer words) / B (manual words) | 0.627 |
| A (customer words) / C (unrelated) | 0.054 |
| B (manual words) / C (unrelated) | 0.024 |

## Look-alike codes with different meanings

- **D**: Alert E-03 is shown on the display.
- **E**: Alert E-08 is shown on the display.

Cosine similarity D / E: **0.869**. E-03 is a saturated pre-filter and E-08 a display fault, yet the sentences are almost identical as vectors. Exact identifiers are where keyword search beats semantic search.
