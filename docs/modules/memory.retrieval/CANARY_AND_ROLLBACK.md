# memory.retrieval canary and rollback

Status: rollout and acceptance contract; the four-mode runtime/controller is not yet fully implemented. These are not currently accepted environment aliases or a claim of a completed canary.

## Promotion ladder

Start with an owner-compatible baseline, then paired shadow execution that cannot affect delivery, then an authenticated deterministic canary cohort, and only then a qualified required profile. Cohort identity, hashing rule, percentage, eligibility and fallback policy are protected versioned configuration. Freeze assignments so retries cannot sample a different policy without an explicit new decision receipt.

A production-state change needs an independent authorized human review of the current non-draft PR head, successful exact-head and fixed-parent synthetic-merge qualification, matching named-host evidence and operator acceptance. Naming a workflow 'required' is not server-side protection; repository administration must enforce the actual contexts and bypass policy. The source branch does not grant that authority.

## Canary evidence

Predeclare quality, safety and resource thresholds. Compare context precision/recall, source validity, OOD/contradiction/abstention rates, stale rejection, delivered-item and assignment agreement, latency percentiles and maximum, request CPU/RSS/allocations, actual SQLite reads, concurrency, owner-write contention and provider rotation. Include failed requests and non-delivery in the denominators. Keep prepared, published, native-started and consumed states separate.

Use [SLO.md](SLO.md) for the nine-stage resource boundary. A microbenchmark, a permanently bypassed ranker/ledger, or a synthetic validator fixture cannot qualify this stage. Report sample size and uncertainty; retain the original workload and thresholds rather than silently adjusting them after results.

## Stop and rollback triggers

Stop admission for any source-revalidation bypass, candidate/receipt mismatch, wrong-generation use, exposure-accounting inconsistency, required-provider failure, hard resource breach, statistically justified quality regression or recovery/epoch inconsistency. Preserve the failed context and release identities in immutable incident evidence.

## Rollback procedure

1. Stop new canary admission through the protected rollout owner, not a request flag.
2. Revoke the candidate context with the protected control capability and its expected epoch. Refresh/reconcile an epoch conflict; never force it.
3. An already-authorized canary rollback may restore its compatibility baseline. **Required-mode failure must not silently downgrade to compatibility**; stop/fail closed unless the external owner explicitly authorizes a different product profile.
4. Preserve source/tree, model/index/policy/lifecycle digests, request-stage outcomes, published context and independent actual-use evidence. Do not rewrite previous learning assignments to pretend a different policy ran.
5. Qualify the exact rollback source and named-host behavior. Reject restoration of an old live provider checkpoint against a newer revocation witness.
6. Resume shadow only after a root-cause regression, current-head independent approval and operator acceptance.

## Rehearsal matrix

Before production acceptance exercise expiry during each asynchronous boundary, same-payload renewal, A/B/A rotation, revocation after preparation, ledger append failure, non-delivery after preparation, concurrent control writers, process crash around durable publication, stale checkpoint restore and unavailable/revoked witness keys. The current in-process tests do not substitute for the durable owner, process-boundary and real consumer tests.
