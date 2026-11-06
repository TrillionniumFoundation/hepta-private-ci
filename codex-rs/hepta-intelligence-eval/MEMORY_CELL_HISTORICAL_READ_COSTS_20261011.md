# MemoryCell: historical reader-cost Pareto controls (2026-10-11)

This is a **read-only analysis of already generated answers**, NOT new
Qwen/Smol inference, independent test data, a lifecycle cost claim, or
production admission. It is intended to make the cost of simpler evidence
selection an explicit competing baseline before parametric-memory investment.

## Exact archived input identities

- Generating commit: `59f9eadd5cc919359079e04442f7343838a60057`.
- Original 8-case event plan SHA-256:
  `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.
- Qwen2.5-3B ZIP SHA-256:
  `831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98`.
- SmolLM2-1.7B ZIP SHA-256:
  `67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae`.
- The archive outer hashes and **all 21 inner manifest members per model**
  were verified. Each includes 48 actual completed model generations;
  saved raw answer/receipt fields match the 48 scored answers.

## Real historical frozen-reader measurements

All rows below are for the SAME 8 authored questions per condition and
frozen reader. Tokens are complete prompt input tokens (not only evidence
tokens); times are sums of original per-answer reader seconds (not cloud
billing, request-level SLO measurements, or end-to-end memory costs).

| Reader | Evidence condition | Strict correct | Prompt tokens | Reader seconds | Original docs |
| --- | --- | ---: | ---: | ---: | ---: |
| Qwen2.5-3B | hybrid top-4 | 3/8 | 10,806 | 120.382 | 32 |
| Qwen2.5-3B | entity/time full-path | 8/8 | 5,752 | 75.880 | 14 |
| Qwen2.5-3B | corrected organized | 8/8 | 5,179 | 71.234 | 12 |
| SmolLM2-1.7B | hybrid top-4 | 1/8 | 11,767 | 134.725 | 32 |
| SmolLM2-1.7B | entity/time full-path | 2/8 | 6,195 | 74.874 | 14 |
| SmolLM2-1.7B | corrected organized | 3/8 | 5,560 | 68.158 | 12 |

### Paired causal bookkeeping

- Qwen: entity/time filtering vs hybrid adds **5/8** task successes and
  avoids **5,054 input tokens (46.77%)** across eight fixed reads.
- Qwen: organized vs entity/time adds **0/8** task successes; it avoids
  **573 input tokens (9.96%)**, and the sum of recorded reader times is
  **4.646 seconds** lower. This is a cost observation, not a graph-specific
  task-accuracy gain or a statistically established speed advantage.
- SmolLM2: organized vs entity/time adds **1/8** task successes and avoids
  **635 input tokens (10.25%)**. The two arms show identical ordered original
  sources for **6/8** cases; only **two correction** cases change the source
  set. This is not a reliable independent superiority estimate.
- The original `entity_time` control **already traverses the complete path**;
  it is not a single-hop baseline. The newer `single_hop` control is needed
  for actual relation-traversal attribution; its unobserved four tasks cannot
  be scored retroactively from this archive.
- `organized` and `program_support` deliver identical source IDs/order on
  **all 8 questions**, so their shared successes cannot be counted as
  two independent demonstrations of organization benefit.

## Qualification and reproducibility limits

The historical ZIPs contain the full source selection, answer, delivered
evidence, input token digest and per-answer resource counters. Sum
`receipt.input_tokens` and `receipt.seconds` for each arm of
`run/scored-answers.json`, after verifying ZIP SHA-256, inner
`SHA256SUMS`, `tested-commit.txt`, and the exact eight-question/6-arm
census. Do not combine Smol and Qwen scores as if they used one reader.

These observations exclude deployed ingestion, retraining, index maintenance,
retention, revocation and disaster-recovery cost. The 8 scopes are authored
and previously exposed; independent future-task generalization, meaningful
parametric-state gain, human-reviewed source sufficiency, semantic citation
precision, and production qualification all remain **unestablished**.
Current next gate remains the pending source-pinned 40-call calibration,
72-call nine-arm Qwen test and independent result replay. On Qwen task
accuracy, the existing corrected-organization control does **not** beat the
full-path entity/time control on the historical eight cases.
