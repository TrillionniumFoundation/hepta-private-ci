# Development-only typo retrieval diagnostic

A failed hypothesis is preserved here: BM25 plus character-trigram rank fusion did not improve a fixed synthetic typo condition and cost more. Both methods scored 25/25 on clean and corrupted development queries. This is not independent-source generalization evidence. Historical learned-routing NO-GO conclusions are unchanged; the separate 72-question sealed test was not read.

Only original diagnostic code, a generic protocol template, and aggregate results are included. No question text, source documents, labels, component IDs, private file paths, model weights, or data assets are published.

## Reproduction

Use Python 3.10+. No third-party dependencies are required. Supply authorized development inputs as `train.jsonl` and `dev.jsonl`; each row contains `query_id`, `group_id`, `query`, `positive_ids`, and `candidates` containing `id` and `text`. Start with a fresh output directory, copy the protocol template there as `protocol.json`, and replace both input hash placeholders before execution.

Run `python run_typo_diagnostic.py --data-dir DATA --output-dir OUTPUT`. The script refuses mismatching input hashes, freezes TRAIN selection before DEV reads, and refuses overwriting existing result receipts. Generated local receipts contain component IDs and must remain private unless separately sanitized.

## Limits

The protocol preceded execution, but source hashing was first persisted after TRAIN selection. Public runner paths were generalized after execution; this is not the byte-identical executed script. Timing includes within-process index construction and scoring, not OS cold process startup. These limitations prevent an independent preregistration or production-benefit claim. See aggregate-result.json for all remaining limits.

Additional limits: zero model calls and sealed-test reads are code/report observations, not independently instrumented access audits. The runner is ordinary single-threaded Python; a two-thread cap is not enforced by the code. The 300-second guard is checked between rows, not an interrupting hard timeout. Timings exclude data loading and process startup; three short repetitions are not a robust hardware benchmark. Independent arithmetic review confirms the recorded calculations but does not remeasure runtime. The published runner has its own hash in aggregate-result.json, distinct from the executed source.
