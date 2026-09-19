# Lane A remaining implementation and external gates

The current-contract documentation and traceability package can be closed by
repository changes. The target architecture and independent acceptance cannot
be declared complete merely by editing this file.

## Repository implementation gates

| Priority | Gate | Current state | Closure evidence required |
| --- | --- | --- | --- |
| P1 | Durable operations ledger/outbox | Not implemented; bounded memory oracle only | transactional backend, same state-machine suite, crash/reopen, corruption, migration and multi-writer tests |
| P1 | AuthBus host trust and recovery | Durable trust revisions plus replay-root/checkpoint verification implemented; external enrollment/distribution and independent checkpoint retention remain | enrolled caller, key ceremony/distribution, trusted time and independently retained restore checkpoint |
| P1 | Authorization policy and quota ledger | Durable policy revisions, conservation-safe reservation and settlement implemented in EvidenceStore; product effect caller/recovery qualification remains | real caller, crash/reopen qualification, provider terminal observer and retained execution receipts |
| P1 | Bao operation/evidence/quota composition | Host composition required | durable intent before dispatch, observed outcome, evidence append and settlement receipts |
| P1 | Authority trusted time and external anti-rollback | Trusted-time input and replay-root checkpoint verification exist; independent source/retention remains external | independently governed time/checkpoint source, atomic host handoff and rollback tests |
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
