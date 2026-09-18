# Lane A remaining implementation and external gates

The current-contract documentation and traceability package can be closed by
repository changes. The target architecture and independent acceptance cannot
be declared complete merely by editing this file.

## Repository implementation gates

| Priority | Gate | Current state | Closure evidence required |
| --- | --- | --- | --- |
| P1 | Durable operations ledger/outbox | Not implemented; bounded memory oracle only | transactional backend, same state-machine suite, crash/reopen, corruption, migration and multi-writer tests |
| P1 | AuthBus host trust and recovery | Managed issuer enrollment/revocation/rotation/retirement and a rollback hash-chain/checkpoint verifier are source-implemented; independently governed checkpoint retention/trusted time remain external | exact-head/merge execution, protected enrolled caller, independently retained restore checkpoint and restore/rollback exercise |
| P1 | Authorization policy and quota ledger | Source candidate implements immutable policy revisions, payload/audience-bound decisions, integer quota conservation and reserve/settle/cancel/expire/quarantine/reconcile | exact-head/merge native receipts, independent semantic review and an enrolled production effect caller |
| P1 | Bao operation/evidence/quota composition | Qualification provider seam now authorizes and reserves before the durable effect boundary and settles Completed only from separate observed-cost evidence; Bao/general production caller remains uncomposed | production caller composition, real observed-cost source, final-use authority, evidence append and settlement receipts |
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
