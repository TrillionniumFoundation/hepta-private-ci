# Kernel operations integrated durable owner V1

## Ownership

The durable source implementation reuses the existing per-Agent CognitiveStore SQLite owner. It does not introduce a second operations database or a second execution spine. `cognitive_operation_ledger` binds operation semantics to the same immutable event/outbox identity already owned by the local lease writer.

## Atomic prepare

`LocalLeaseOutbox::admit_operation` validates the complete `OperationIntent`, acquires `BEGIN IMMEDIATE`, verifies the current lease and journal chains, then inserts the admitted local event, immutable local outbox row and immutable operation row before one commit. Fault injection after every insert proves rollback leaves no partial identity.

## Dispatch and ambiguity

`ProductionDurableWriter` verifies the queued receipt and exact durable operation/destination binding. Before any target call it writes the strict one-shot indeterminate dispatch claim. An exact replay of that claim is rejected. A crash or acknowledgement loss therefore reopens as unresolved work and must reconcile rather than resend.

## Final-use authority

`ProductionFinalUseOutboxDispatcher` validates the exact `FinalUseBinding`, consumes a signed single-use grant through `FinalUseAuthority::claim`, and invokes `with_verified_use` immediately around target entry. The token never becomes a wire credential.

## Owner handoff

A queued identity admitted under a terminal predecessor generation can be recovered by a successor without a second event/outbox row. `claim_inherited_dispatch` writes the successor's durable indeterminate claim before target entry. Already-indeterminate work can be reconciled under the current valid owner after predecessor terminalization.

## Real destination

`CognitiveSourceOutboxTarget` is the first real destination slice. Apply is destination-owned through the CognitiveStore source ledger. Exact replay returns the same destination fact; payload drift is rejected. `observe_terminal` queries destination-owned state rather than trusting transport acknowledgement.

## Crash and corruption evidence

The source suite contains transaction fault injection, reopen/tamper tests, concurrent-dispatch exclusion, post-send crash/indeterminate recovery and a qualification-only child-process kill/reopen probe. The latter intentionally does not claim physical host power-loss durability.

## Retention boundary

The operation metadata is not constrained by the 16,384-record reference-oracle ceiling. The authoritative local lease/event/outbox journals remain immutable hash chains. This V1 does not delete historical journal rows. Physical bounded-history retention requires a separately versioned segment/checkpoint compaction protocol; deleting rows in place would destroy reopen/audit evidence.

## Claim ceiling

This document establishes source implementation only. Default product activation, target-host power-loss/storage qualification, independent acceptance, promotion and release remain separate gates.
