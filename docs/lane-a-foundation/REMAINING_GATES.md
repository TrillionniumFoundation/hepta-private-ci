# Lane A remaining implementation and external gates

The current-contract documentation and traceability package can be closed by
repository changes. The target architecture and independent acceptance cannot
be declared complete merely by editing this file.

## Repository implementation gates

| Priority | Gate | Current state | Closure evidence required |
| --- | --- | --- | --- |
| P1 | Durable operations ledger/outbox | Not implemented; bounded memory oracle only | transactional backend, same state-machine suite, crash/reopen, corruption, migration and multi-writer tests |
| P1 | AuthBus host trust and recovery | Candidate source adds monotonic trust schema v2, full projection digest, replay checkpoints and safe retired-epoch compaction; external checkpoint custody and issuer private-key lifecycle remain operator-governed | exact-head/merge receipts, managed issuer keys/revocation, trusted time and independently retained restore checkpoint |
| P1 | Authorization policy and quota ledger | Candidate source implemented in the existing evidence SQLite owner: versioned policy, atomic quota reservation, conservative settlement/reconciliation and BUS-01..04 tests; production effect caller not activated | exact-head/merge candidate receipts, independent semantic review and a named production effect caller |
| P1 | Bao operation/evidence/quota composition | Host composition required | durable intent before dispatch, observed outcome, evidence append and settlement receipts |
| P1 | Authority trusted time and external anti-rollback | Replay rollback can now be fenced by an independently supplied checkpoint and rollback tests exist; wall-clock trust and independent checkpoint storage remain external | independently governed time/checkpoint source plus retained target-host restore receipts |
| P1 | Cross-language wire/authority conformance | Rust source vector only | independent client implementations and golden-vector execution |
| P2 | Fuzz, disk-full and fault campaigns | Partial | retained exact-candidate fuzz/crash/fault receipts |
| P2 | Capacity and recovery measurements | Not accepted | measured budgets on named target hosts |

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
source SHA, source tree, evaluator identity, scope, validity window and
revocation status.
