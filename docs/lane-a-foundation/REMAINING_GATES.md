# Lane A remaining implementation and external gates

The current-contract documentation and traceability package can be closed by
repository changes. Source implementation, exact-candidate execution, activation
and independently governed acceptance remain distinct states.

## Repository implementation gates

| Priority | Gate | Current state | Closure evidence required |
| --- | --- | --- | --- |
| P1 | Durable operations ledger/outbox | Not implemented; `kernel.operations` remains a bounded in-memory reference model | transactional owner, crash/reopen/corruption/multi-writer tests, then bind its operation receipt into the current AuthBus/Bao path |
| P1 | AuthBus signed ingress/replay recovery | Source-implemented Agentd caller plus external replay-checkpoint protocol | unchanged exact-head/synthetic-merge process tests, target-host restore/power-loss evidence and independently provisioned trust/checkpoint inputs |
| P1 | AuthBus authorization/quota/reservation owner | Source-implemented durable policy history, signed trusted time, quota reservation/cancel/settle, restart reconciler, terminal archive and authority anti-rollback witness | unchanged exact-head/synthetic-merge tests, target-host fault/capacity qualification and independent security review |
| P1 | Bao operation/final-use/quota composition | Bounded KV-v2 read is source-composed through AuthBus reserve -> dispatch fence -> kernel final-use -> signed settlement; ambiguous outcome holds quota | durable `kernel.operations` owner binding, exact product-test receipt and real provider/operator qualification |
| P1 | External trust/time/checkpoint operation | Verification and fail-closed protocols are source-implemented | independently operated issuer/key ceremony, trusted-time source, checkpoint retention/backup policy, revocation delivery and restore drill |
| P1 | Cross-language wire/authority conformance | Rust source vector only | independent client implementations and golden-vector execution |
| P2 | Fuzz, disk-full and fault campaigns | Partial; deterministic rollback/restart/ack-loss cases exist | retained disk-full/fsync/rename/corruption/fuzz receipts on the exact candidate |
| P2 | Capacity and recovery measurements | Not accepted | measured contention, checkpoint cost, reconciliation backlog, SQLite size/RSS and p50/p95/p99 on named target hosts |

## Independently governed gates

The repository cannot self-grant these states:

- independent non-author security and semantic review;
- production caller enrollment and protected configuration;
- external trust-root and key-rotation ceremony;
- real provider/operator consent;
- physical-platform or hardware qualification where applicable;
- operator acceptance;
- selection, promotion and release.

An external gate closes only through an authenticated receipt naming the exact
source SHA/tree (or registered implementation-source identity where explicitly
defined), evaluator identity, scope, validity window and revocation status.
