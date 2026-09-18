# Lane A remaining implementation and external gates

The current-contract documentation and traceability package can be closed by
repository changes. The target architecture and independent acceptance cannot
be declared complete merely by editing this file.

## Repository implementation gates

| Priority | Gate | Current state | Closure evidence required |
| --- | --- | --- | --- |
| P1 | Durable operations ledger/outbox | Not implemented; bounded memory oracle only | transactional backend, same state-machine suite, crash/reopen, corruption, migration and multi-writer tests |
| P1 | AuthBus host trust and recovery | Candidate adds bounded overlapping key epochs, external restore-checkpoint verification and replay-epoch tombstones; production provisioning/retention remains | enrolled caller, independently retained checkpoint service/file, managed issuer ceremony, trusted time and target-host rollback test |
| P1 | Authorization policy and quota ledger | Source candidate implemented in EvidenceStore migration 0011 with BUS-01..04 tests; no registered external-effect caller/acceptance yet | exact-head + synthetic-merge pass, independent semantic review, real effect caller and target-host crash/reopen qualification |
| P1 | Bao operation/evidence/quota composition | Host composition still required; AuthBus now exposes authorize+reserve, final-use validation and observed settlement primitives | wire the registered adapter through those primitives, durable intent before dispatch, observed outcome, evidence append and settlement receipts |
| P1 | Authority trusted time and external anti-rollback | Local wall clock/filesystem only | independently governed time/checkpoint source and rollback tests |
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
