# kernel.operations product composition V1

## Claim level

This document records a **source-integrated host composition**, not production
activation or independent acceptance.

The source-side durable owner remains `kernel.operations::DurableOperationStore`.
The destination owner is the existing `cognitive.store::CognitiveStore`,
entered only through the existing `ProductionDurableWriter` authority/fence.
`runtime.agentd::AgentdOperationCoordinator` sequences the two owners but owns
neither store.

## Source transaction and payload recovery

`DurableOperationStore::prepare_intent` atomically commits the operation ledger
and source outbox together with the exact bounded payload bytes. A restarted
dispatcher recovers those bytes from the source outbox and verifies their
payload digest before a claim is returned.

A claim is generation/authority/fence bound. Same-generation authority epoch
rotation invalidates older claims; pending work may be requeued under the newer
epoch, while already-dispatched work becomes `Indeterminate`.

## Destination-owned atomic apply and dedupe

The CognitiveStore migration
`0011_cross_owner_operation_inbox.sql` adds the append-only
`cognitive_cross_owner_operations` inbox.

One destination transaction binds:

- stable operation ID;
- source owner ID;
- source semantic digest;
- exact payload digest and bytes;
- destination owner agent ID;
- terminal receipt digest and apply time.

The same operation ID and exact semantic/payload identity is idempotent.
Identity reuse with changed semantics or payload conflicts. Update/delete is
denied by schema triggers. Reopen recomputes payload and receipt digests and
fails closed on missing required inbox schema objects.

## Agentd sequence

For the CognitiveStore destination, the source-integrated sequence is:

1. prepare durable source ledger + outbox;
2. claim with current Agentd production-writer generation/authority epoch;
3. commit source `record_dispatch_started`;
4. revalidate the existing `ProductionDurableWriter` authority and writer
   fence;
5. atomically dedupe/apply the exact payload in the destination CognitiveStore;
6. settle the source operation from the destination receipt digest.

If step 5 returns an error after dispatch-start, Agentd attempts to persist
`Indeterminate` and does not requeue the operation.

If the source misses the destination result, reconciliation queries the
destination-owned inbox. An exact receipt settles `Applied`; an authoritative
absence settles `NotApplied`; an unavailable or conflicting destination
observation leaves the source unresolved/indeterminate.

## Authority boundary

This V1 local CognitiveStore destination uses the repository's existing
`ProductionDurableWriter` opaque authority token, authority epoch, generation
and fencing token. It does **not** claim that a local SQLite owner boundary is an
external provider effect.

For network/provider/tool/filesystem/secret destinations,
`kernel.authority::FinalUseAuthority` remains mandatory at the actual external
adapter boundary. The source operation store cannot mint or substitute that
authority.

## Verification source

The composition source is:

- `codex-rs/hepta-agentd/src/operations_writer_bridge.rs`;
- `codex-rs/hepta-memory/src/cross_owner_operation.rs`;
- `codex-rs/hepta-memory/migrations/0011_cross_owner_operation_inbox.sql`.

Focused source tests cover:

- real CognitiveStore destination apply and destination-owned exact replay
  deduplication;
- source-result loss followed by destination observation and terminal
  reconciliation without resend;
- committed source dispatch with authoritative destination absence settling
  `NotApplied`;
- destination payload drift/conflict;
- destination reopen observation;
- append-only destination receipt enforcement.

These are source test identities until exact-head and synthetic-merge CI records
are retained.

## Remaining gates

This composition does not by itself set module
`productionImplementation=true`. Remaining gates include:

- default/runtime construction and lifecycle ownership of
  `AgentdOperationCoordinator`;
- actual external-adapter final-use composition for non-local destinations;
- target-host disk-full/I/O/backup-restore/performance evidence;
- independent semantic/security review;
- activation, canary, promotion and release.
