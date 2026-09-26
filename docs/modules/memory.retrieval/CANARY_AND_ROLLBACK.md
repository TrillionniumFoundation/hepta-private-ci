# memory.retrieval canary and rollback

## Promotion ladder

1. **compatibility baseline** — record owner-ranked outputs and SLOs.
2. **shadow** — run the exact HNMF/vector path, retain comparison receipts, deliver compatibility output only.
3. **canary** — admit a deterministic, authenticated cohort. The cohort key and percentage are protected configuration and part of the release receipt.
4. **required** — all eligible traffic uses the current leased context; any absence or mismatch fails closed.

No stage may be skipped. A production-state change requires a non-author approval and green exact-head plus ordered-parent synthetic-merge receipts.

## Canary acceptance

Compare compatibility and candidate paths on:

- context precision/recall and source validity;
- abstention, OOD and contradiction rates;
- stale-context rejection;
- delivered-item and learning-assignment agreement;
- p50/p95/p99/max latency;
- CPU, peak RSS and allocation count;
- SQLite reads and owner write contention;
- provider rotation contention;
- error and timeout rates.

Predeclare thresholds. Do not tune thresholds after inspecting the same canary sample.

## Automatic rollback triggers

- any safety invariant violation;
- candidate/receipt count mismatch;
- source revalidation bypass or stale context exposure;
- learning assignment says exposed when no item was delivered, or the reverse;
- p99 or peak RSS above the approved hard limit;
- statistically material increase in unsafe retrieval or negative-transfer outcome;
- provider epoch, lease or recovery digest inconsistency.

## Rollback procedure

1. Stop new canary admission.
2. Revoke the current product context using its expected epoch.
3. Restore compatibility delivery; do not reuse the revoked provider.
4. Preserve all affected request, retrieval, context-plan and learning receipts.
5. Re-run exact-head qualification on the rollback revision.
6. Open an incident with source commit/tree, provider epoch and model/index/policy digests.
7. Resume shadow only after root cause, regression test and independent approval.

Rollback changes delivery, not history. Existing learning evidence remains immutable and must be marked with the release/context digest that produced it.
