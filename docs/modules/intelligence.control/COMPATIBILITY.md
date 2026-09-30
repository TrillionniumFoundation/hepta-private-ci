# intelligence.control compatibility and migration contract

Parent: [TECHNICAL.md](TECHNICAL.md). This document defines source and persisted
state compatibility; it does not authorize product activation.

## Public source compatibility

The canonical product path is the authenticated `ObjectiveStart` route with a
host-owned invocation provider and, when physically composed, one
`AgentdIntelligenceExecutionHostV1`. Compatibility/shadow entrypoints may remain
for migration but cannot advertise canonical capability or bypass currentness,
permission, lease, provider-entry or learning acknowledgement checks.

New public APIs must preserve the existing operation identity and effect-boundary
semantics. Renames require a deprecation window or an atomic update of every
tracked caller. Consumer compilation is part of the exact-head qualification.

## Durable compatibility

SQLite migrations are append-only and versioned. Existing semantic digests,
operation IDs, terminal evidence, outbox fences, attempt counts and tombstones
must remain readable after upgrade. A migration may not reinterpret
`Dispatching`, `Dispatched` or `Indeterminate` as safe-to-retry. Unknown enum or
schema values fail as corruption rather than falling back to a permissive state.

`DurableOperationClock` changes clock ownership, not the persisted timestamp
format. Values remain Unix milliseconds and rollback remains fail-closed.

## Upgrade procedure

1. Freeze an exact candidate and retain a backup plus its digest.
2. Run migrations and quick/invariant checks on an isolated copy.
3. Reopen old pending, leased, indeterminate and terminal fixtures.
4. Verify same-identity replay, stale-owner fencing, destination-first recovery
   and tombstone non-resurrection.
5. Execute source-head and synthetic-merge qualification with the final lockfile.
6. Roll forward only after independent acceptance; otherwise restore the intact
   backup and keep admission closed.

## Versioning policy

Wire and persisted schema changes require explicit version fields, migration
tests and a compatibility note here. Evidence and status schemas may advance
independently, but a verifier must reject an unknown schema rather than treating
it as a pass. Acceptance receipts bind their verifier and workflow SHA, so a
verifier change invalidates previous candidate acceptance.
