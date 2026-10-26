# Relevance-gate threshold calibration (Task 06)

Run: 2026-10-26 08:56 UTC. Embedding model: `text-embedding-3-small`. Score: cosine similarity of the best retrieved chunk. Calibration questions are separate from the evaluation test set.

**Recommended threshold: 0.34**, the midpoint of the highest off-topic score (0.192) and the lowest answerable score (0.491).

## Best-chunk similarity by group

| Group | Questions | Min | Median | Max |
|---|---|---|---|---|
| answerable | 15 | 0.491 | 0.644 | 0.776 |
| gap | 8 | 0.304 | 0.445 | 0.691 |
| off_topic | 6 | 0.072 | 0.157 | 0.192 |

## Sweep

Answerable: passed the gate (higher is better). Gap and off-topic: refused by the gate.

| Threshold | Answerable passed | Gap refused | Off-topic refused |
|---|---|---|---|
| 0.100 | 15/15 | 0/8 | 1/6 |
| 0.125 | 15/15 | 0/8 | 1/6 |
| 0.150 | 15/15 | 0/8 | 3/6 |
| 0.175 | 15/15 | 0/8 | 5/6 |
| 0.200 | 15/15 | 0/8 | 6/6 |
| 0.225 | 15/15 | 0/8 | 6/6 |
| 0.250 | 15/15 | 0/8 | 6/6 |
| 0.275 | 15/15 | 0/8 | 6/6 |
| 0.300 | 15/15 | 0/8 | 6/6 |
| 0.325 | 15/15 | 1/8 | 6/6 |
| 0.340 **(recommended)** | 15/15 | 1/8 | 6/6 |
| 0.350 | 15/15 | 1/8 | 6/6 |
| 0.375 | 15/15 | 1/8 | 6/6 |
| 0.400 | 15/15 | 1/8 | 6/6 |
| 0.425 | 15/15 | 1/8 | 6/6 |
| 0.450 | 15/15 | 4/8 | 6/6 |
| 0.475 | 15/15 | 6/8 | 6/6 |
| 0.500 | 14/15 | 6/8 | 6/6 |
| 0.525 | 12/15 | 6/8 | 6/6 |
| 0.550 | 12/15 | 6/8 | 6/6 |
| 0.575 | 10/15 | 6/8 | 6/6 |
| 0.600 | 8/15 | 6/8 | 6/6 |

## Every question

| Group | Question | Best similarity |
|---|---|---|
| answerable | What is the maximum inlet water pressure? | 0.491 |
| answerable | Is international shipping available? | 0.508 |
| answerable | What does a blue flashing UV light mean? | 0.519 |
| answerable | How long do card refunds take? | 0.566 |
| answerable | What does the Premium maintenance plan include? | 0.568 |
| answerable | Who do I contact about a privacy request? | 0.579 |
| answerable | What is the restocking fee for an opened item? | 0.592 |
| answerable | How often should I replace the carbon block? | 0.644 |
| answerable | What tools do I need to mount the purifier on the wall? | 0.661 |
| answerable | What happens if the courier can't deliver my parcel? | 0.663 |
| answerable | How do I delete my account in the app? | 0.672 |
| answerable | What is the tank capacity of the AquaPearl 500 Pro? | 0.672 |
| answerable | Can I transfer the warranty if I sell my purifier? | 0.696 |
| answerable | How do I pair the purifier with my phone? | 0.731 |
| answerable | How much is the HEPA filter for the AeroPearl Mini? | 0.776 |
| gap | Is there a discount for university students or teachers? | 0.304 |
| gap | Do you offer EMI or buy now pay later? | 0.425 |
| gap | Is the purified water OK for mixing infant formula? | 0.428 |
| gap | Does the purifier have NSF/ANSI 58 certification? | 0.430 |
| gap | Do you have a physical showroom in Karachi? | 0.461 |
| gap | Can I rent a purifier instead of buying one? | 0.474 |
| gap | Will the AquaPearl remove lead and arsenic from my water? | 0.630 |
| gap | What is the warranty on the Pearlz water softener? | 0.691 |
| off_topic | What's the capital of France? | 0.072 |
| off_topic | How do I bake a chocolate cake? | 0.140 |
| off_topic | Who won the cricket world cup in 2011? | 0.144 |
| off_topic | What's the dollar exchange rate today? | 0.170 |
| off_topic | Recommend a good laptop for programming. | 0.175 |
| off_topic | Write me a poem about the sea. | 0.192 |
