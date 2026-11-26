# P0 Cell Split execution-owner contract (proposed, not production-qualified)

Status: **design gate only**. This document grants **no** authority for a topology mutation, release, or physical split. No source, build, CI, or target-host evidence is implied by committing it.

## Ownership and authority

Exactly one execution owner per `(scope, parent_cell, parent_generation, candidate_id)` holds a fenced lease. A separate evaluator produces an evaluation receipt, a selector records a decision, and an independent authority signer issues a scoped, expiring final-use authorization. The execution owner **never signs its own authorization**. A production caller must reject any attempt to bypass these roles.

A split attempt carries: immutable parent state/checkpoint reference; proposed child identity and next generation; frozen no-change baseline; artifact manifest and digests; scope; lease epoch; request/idempotency key; observer witness identity; monotonic ledger sequence.

## Durable transitions and evidence

| State | Required external operation | Verifiable evidence before advancement |
| --- | --- | --- |
| IntentRecorded | Append split intent to durable ledger | fsync/commit acknowledgement for exact attempt |
| ArtifactReady | Write and read back the actual artifact in CAS | CAS write receipt, read-back match, independently validated artifact signature |
| ChildMigrated | Run state transform and commit child checkpoint | checkpoint-store commit receipt, schema/version and source/target generations, read-back |
| ShadowObserved | Start non-routable child and evaluate future-window data | independent evaluator receipt bound to frozen no-change and negative transfer |
| Selected | Selector chooses promote or reject using NDU and resource costs | signed or otherwise independently authenticated selection receipt; rejects are terminal |
| Authorized | Independent final-use gate validates a short-lived authorization | scope, candidate, exact artifact, generations, lease epoch, route target, expiration, revocation |
| ParentFenced | Supervisor fences stale parent writers before mutation | durable Supervisor fence receipt, current generation read-back |
| RouteCommitted | CNS compare-and-swap route from exact expected parent generation to child | actual CNS CAS receipt and independently fetched route state |
| Completed | Append terminal ledger receipt and observer witness | durable terminal acknowledgement plus read-back of route/fence/child state |

A digest alone is never operational proof. Each receipt must bind an operation-specific idempotency key, attempt ID, external authority identity and the observed committed revision. All receipts must be independently checked, not merely deserialized or hash-matched.

## Recovery and ambiguity

1. Persist *intent before each effect*, then execute with the same stable idempotency key. Never reissue a non-idempotent operation with a new key on retry.
2. On owner restart, acquire a strictly newer fenced lease, replay the ledger, then **query authoritative external systems** for CAS, checkpoint, Supervisor and CNS status. Treat cached state as advisory.
3. For an unknown external outcome, mark `Indeterminate`, quarantine the child and block further route mutations until reconciliation. Do not infer success from an intent, client timeout or local digest.
4. If no route cutover occurred, keep parent routing unchanged and tombstone the unpromoted child after verified cleanup. Do not erase receipts.
5. Once CNS cutover committed, **never blindly roll back**. A compensating cutover requires its own current-generation CAS, fresh authority, read-back and durable receipt. Old parent writers remain fenced.
6. A stale lease, stale generation, revoked/expired authorization, absent independent evaluator/selector, mismatched scope or missing observer witness is fail-closed.
7. Ledger corruption outside a documented, checksummed, uncommitted tail is fatal and must not be silently truncated.

## Required fault-injection acceptance matrix

Test crash-before-effect, crash-after-effect-before-ledger-ack, duplicate request, timeout-with-unknown-result and stale-generation replay independently for CAS, checkpoint, Supervisor fence and CNS cutover. Include conflicting concurrent owners, expired/revoked authorization, incompatible checkpoint schema, read-back divergence, evaluator/selector identity collision and observer outage.

Assertions:
- at most one routable generation per exact scope/cell at any externally observable instant;
- no route points to a child without a verified checkpoint and artifact;
- no old writer can commit after a committed fence;
- retries are idempotent and reconcile externally rather than claim success from a digest;
- an indeterminate state never produces a promotion;
- all terminal states retain independently inspectable evidence.

## NDU and physical-split gate

Freeze the no-change baseline **before** candidate execution. Independent evaluation must report future-window utility delta, negative-transfer rate, cold/warm resource cost, safety regression and uncertainty. A positive point estimate alone cannot authorize promotion.

No physical split is permitted until the exact target-host workload has all 16 preregistered combinations with matched data, seed, host, compiler/runtime, encoder and model revision. Record p50/p95/p99, throughput, CPU/RSS/GPU, transmitted bytes, fsync latency/count, lock waits, recovery time and long-term negative migration. Attach raw observer receipts and CI SHA; synthetic fixtures are not production evidence.

## Integration boundary

Implement the state machine in a **single product execution owner**, not in `codex-hepta-neuron`: that crate's current declared role is deterministic/qualification runtime without promotion or effect authority. Adapters for Artifact CAS, checkpoint owner, Supervisor, CNS, ledger and independent authorization must provide actual operation receipts and read-back APIs. Do not widen Neuron authority to satisfy the split contract.

Next deliverable: product-owner implementation with receipt-bearing adapter traits, durable ledger journal, restart reconciliation, crash-injection tests and observed native CI. Until then: **P0 blocked / production routing disabled**.
