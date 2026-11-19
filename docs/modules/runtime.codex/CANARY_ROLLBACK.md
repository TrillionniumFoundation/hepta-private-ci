# runtime.codex canary and rollback

## Canary admission

Use a distinct deployment generation and bounded operation cohort. Start with model-only requests that have deterministic harmless outputs and no external tools. Require exact provider request counting, final-use grants, durable terminal correlation, owner readiness, and clean reconciliation before increasing traffic.

Stop the canary on any duplicate request, blind replay, unbounded queue, authority rollback, process identity drift, unresolved-history growth, schema mismatch, p95/p99 breach, or inability to drain without discarding an unresolved operation.

## Rollback

1. Close admission for the candidate generation.
2. Drain or quarantine every admitted operation; never reinterpret process loss as unsent.
3. Preserve candidate journals, authority heads, operation IDs, and receipts.
4. Restore a binary compatible with the durable schema and pending record semantics.
5. Reconcile before opening the predecessor generation.
6. Verify the predecessor cannot reuse candidate nonces, generations, connection IDs, or operation identities.

A rollback across a schema or authority epoch requires an explicit migration/recovery procedure and external anti-rollback evidence. Copying an older authority store or revocation head is prohibited.

## Promotion

Promotion requires the protected target qualification receipt, reviewed p95/p99 baseline, successful canary, rehearsed rollback, zero unresolved correctness violations, and independent acceptance. The source repository, workflow author, runtime worker, Agentd, and final-use issuer cannot self-approve promotion or release.
