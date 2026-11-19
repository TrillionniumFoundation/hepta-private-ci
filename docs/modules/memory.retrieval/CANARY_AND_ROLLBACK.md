# memory.retrieval canary and rollback

## Rollout sequence

1. **Compatibility:** establish owner-path correctness, observability and baseline delivery.
2. **Shadow:** evaluate every request with the same current HNMF context while preserving compatibility delivery. Record HNMF assignment with no exposure and compare rank, abstention and stale-context behavior.
3. **Canary:** deterministically apply HNMF to the declared bounded fraction; all nonselected requests remain shadow. Sampling is stable for one request identity and has no hidden mutable percentage.
4. **Required:** apply HNMF to all requests only after semantic, SLO, provider, vector-owner, review and operator gates pass.

## Promotion gates

Promotion requires no correctness regression; bounded false-abstention and stale-context rates; exact source/merge receipts; approved target-host SLO; lease rotation/revocation/recovery tests; delivered-set learning evidence; and independent current-head approval. CI success alone is insufficient.

## Rollback

Rollback changes protected product configuration to compatibility, revokes the active provider, stops new HNMF exposures and preserves exact receipts. It does not rewrite historical assignments, delete evidence or silently reinterpret a previous mode. If a schema or durable format changed, restore only a binary/state pair proven compatible; retrieval itself owns no durable content schema.

## Stop conditions

Immediately stop canary on owner revalidation conflict, generation drift, provider expiry/revocation, Vector owner absence, receipt/count mismatch, zero-activation support, same-side contradiction false abstention, p99/RSS limit breach, learning append loss or inability to reproduce the exact candidate.
