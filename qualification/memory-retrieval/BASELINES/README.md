# Content-addressed retrieval baseline evidence

Raw historical archives belong under `<archive-sha256>/archive.zip`, accompanied by `receipt.json`. Run `scripts/hepta_memory_retrieval_archive.py verify <receipt.json>` before use. The archive importer checks member names, sizes, duplicates, source identity and exact measurement phases; a retained archive is not a product or release acceptance receipt.

`HISTORICAL-20260921.json` is a locally verified summary of the original ZIP, retaining its SHA-256, member hashes and measured values. The raw ZIP has not been stored in this Git tree; its hosted artifact expires on 2026-10-21. Import the separately supplied original ZIP using the archive tool before claiming durable raw-log availability. This is a durable summary receipt, not complete raw-evidence retention.

The September 21 qualification archive at source `b1cc91cdaa2475aa123105bcc1d323cd3fe9323d` contains separate SQLite and HNMF probes. It does not measure current-head Agentd E2E latency. Do not add its separate percentiles or treat its old source as current.

New E2E samples must bind a preapproved `hepta.memory-retrieval.slo-policy.v1` and use `hepta.memory-retrieval.e2e-samples.v1`. Required stages: sqlite_observation, snapshot_binding, candidate_adaptation, hnmf_settling, downstream_ranker, final_revalidation, text_materialization, context_plan, learning_assignment_append. Record exclusive monotonic durations and separately measured total wall time.

Include CPU time, peak RSS, allocation/SQLite read counts, candidate/node/synapse/traversal counts, cache state, concurrency, owner-write/provider-rotation contention, abstention and stale-rejection outcomes. Missing measurements are unavailable, not zero. Process-wide counters must not be double-counted across concurrent requests. Preserve the producer/instrumentation identity, raw samples and measured workload duration so throughput can be computed from actual elapsed time.

Run `python3 scripts/hepta_memory_retrieval_slo.py --samples samples.json --policy approved-policy.json --head <exact-sha> --output-dir <receipt-directory>`. This command validates/retains observations; it is not the missing product instrumentation and does not approve its own thresholds. Keep incomplete host cases visibly unqualified.

Tracked blobs and hashes outlive Actions artifact expiration. Administrator-proof retention still requires an independently governed object-lock store and external receipt; no such store is provisioned by this source change.
