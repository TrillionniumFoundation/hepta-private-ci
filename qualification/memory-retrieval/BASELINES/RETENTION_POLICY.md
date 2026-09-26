# Benchmark evidence retention and promotion

No baseline in this directory becomes current qualification by being copied, renamed or listed in an implementation map. Match the exact source/tree, complete workload, compiler, host architecture, cache/concurrency state and immutable threshold bytes.

Use a content-addressed record layout such as:

```
<source-sha>/<host-profile>/<receipt-sha256>/
  receipt.json
  raw-logs/
  per-request-samples/
  thresholds.json
  SHA256SUMS
  acceptance.json
```

Create new records; never overwrite an old measurement under its previous key. `verify_memory_retrieval_slo.py` uses exclusive-create plus file/directory fsync for its output and binds log/threshold/source hashes. This is local publication protection, not an externally enforced object lock. An approved long-term owner must retain the raw bytes and issue an independently verified archive acceptance receipt.

GitHub Actions uploads currently request 90 days, subject to repository policy. They remain expiring evidence. A historical source artifact can be retained in Git for reproducibility, but that is not a named-host E2E result or external WORM guarantee. Retain its original source identity and mark it historical; do not rewrite it with the current head.

Promotion requires an authorized independent reviewer of the current non-draft PR head, exact-head and deterministic synthetic-merge passes, matching-host predeclared thresholds, and separate operator/release acceptance. Neither the source exporter, Python parser fixtures nor the archive job grants production authority.
