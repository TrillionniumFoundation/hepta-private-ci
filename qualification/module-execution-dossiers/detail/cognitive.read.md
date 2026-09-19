# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: exact-ID typed-local read port, canonical SQLite-cut adapter, Agentd product consumer and final-use revalidation are source implemented; exact-candidate execution evidence and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-read`.
Package: `MEM-READ-1-SNAPSHOT-PORT`.

The read module owns no durable facts, writer, SQL connection, cache service or background synchronization loop. The authoritative physical owner remains `hepta-memory::CognitiveStore` and its existing `cognitive_1.sqlite3`.

## 2. Public operations and contract details

The implemented product path is:

```text
CognitiveStore::lane_c_snapshot(scope)
→ DurableCognitiveSnapshot
→ read_ids_v1(snapshot, ids, fields)
→ bounded selected content
→ Agentd CognitiveContext
→ capability-gated CognitiveContextRevalidate
→ physical model TurnStart
```

`read_ids_v1` is the native typed-local implementation of the registered `ModulePort::cognitive.read::*` contracts. It accepts at most 512 stable IDs, explicitly selects projection fields, reports missing IDs, binds the exact request and result digest, and never grants effect authority. It is all-or-error under the selected encoded-byte limit; it does not silently prefix-truncate an exact-ID request.

`read_v2` remains a compatibility/library projection and deterministic canonical byte format. Its bytes are not a registered wire protocol or durable format. A future cross-process cognitive-read format requires separate protocol admission rather than silently treating the V2 bytes as wire.

Final-use revalidation is carried by the existing Agentd local control protocol as the additive capability `cognitive.context.revalidate@1`. The pre-existing `CognitiveContextSnapshot` response shape remains unchanged. A consumer that cannot negotiate final-use revalidation must not attach cognitive context to the model.

## 3. State records and transaction design

`cognitive.read` is stateless. It owns no projection cache, pin table, lease ledger, descriptor pool or cancellation registry.

The SQLite owner acquires one authorized read transaction, validates bounded ancestry/citations/frontiers, materializes the immutable snapshot value, and commits the read transaction before returning it. Cancellation or drop therefore releases only ordinary in-memory values; there is no long-lived read pin to release.

A host may introduce a cache only through a separately specified component whose key binds principal, scope, source snapshot and revocation-relevant identities. No such cache is part of the current module and no cache behavior is claimed here.

## 4. Deterministic algorithm and scheduling

1. Authenticate owner/scope at `CognitiveStore::lane_c_snapshot`.
2. Retrieve a bounded candidate set through the existing store owner.
3. Convert candidate memory IDs into a bounded exact-ID request.
4. Build the snapshot's current-head map once and resolve requested IDs from that map.
5. Require live state plus exact memory ID, revision and content digest before content admission.
6. Rank only admitted items.
7. Apply the shared final consumer byte budget.
8. Revalidate the owner snapshot before returning Agentd context.
9. Immediately before physical `TurnStart`, require `cognitive.context.revalidate@1`, reacquire the current owner snapshot and recheck every selected ID/revision/content digest and the exact snapshot digest.
10. Any correction, committed tombstone, validity expiry, scope mismatch, content substitution or generation change fails closed.

This removes the former global-first-1024 projection intersection. A relevant candidate is no longer rejected merely because its ID sorts after the legacy `read_v2` prefix.

The final-use check is a current observation, not a lease over future writes. The system still does not claim an atomic lock over the external provider after the check.

## 5. Capacity and performance profile

- exact-ID request: <= 512 IDs;
- generic module-native V2 envelope: <= 1 MiB;
- current composed Agentd/model context: one shared 8 KiB serialized budget;
- durable owner snapshot: bounded by the limits in `codex-rs/hepta-memory/LANE_C_SQLITE.md`;
- current Agentd retrieval result limit: 1..=4 selected memories.

Exact-ID validation builds one canonical current-head map and then performs keyed lookup instead of scanning every read record for every candidate. The source contains capacity regressions, not production latency measurements. p50/p95/p99 CPU/RSS/SQLite measurements remain target-host qualification evidence and must not be inferred from these bounds.

## 6. Concrete verification cases

- **READ-01 stale-final-use:** obtain context, then correct/forget/expire a selected memory; final-use revalidation rejects the old context.
- **READ-02 exact-ID beyond prefix:** request a current memory whose canonical ID lies after 1,024 other records; exact-ID read still returns it.
- **READ-03 scope/no-cache:** a different principal cannot acquire the owner cut; the module has no cross-principal cache surface.
- **READ-04 exact-ID resource bound:** duplicate IDs, >512 IDs or an encoded result over the selected bound fail instead of returning a partial exact-ID set.
- **READ-05 capability gate:** model attachment with cognitive context requires `cognitive.context.revalidate@1`; absence of the capability fails before provider dispatch.
- **READ-06 tombstone lineage:** a complete tombstone-to-live resurrection fails closed and a committed terminal tombstone cannot be attached.

These are source test obligations. A test identity is not an exact-candidate pass receipt or independent acceptance.

## 7. Integration, rollback and capability ceiling

The durable SQLite owner is the only product snapshot source. `DurableCognitiveSnapshot` is therefore the canonical product-native owner boundary.

`AuthoritativeCognitiveSnapshotProvider` remains a generic synchronous library/test abstraction for callers that already possess a fully bound `AuthoritativeSnapshotV1`; it is not a second product owner, database or competing acquisition path. Product composition must not manufacture a snapshot through that trait when the durable owner is available.

The current SQLite memory schema has no persisted memory-kind discriminator. Its durable Lane C projection explicitly supports `MemoryKind::Fact` only. `Episode`, `Preference` and `Procedure` remain valid cognitive type values for other sources, but durable callers must not claim those kinds until the owner schema, migration and compatibility evidence add them.

Rollback removes the new Agentd capability and exact-ID consumer together or restores the predecessor product path. No rollback may reinterpret V2 canonical bytes as a wire protocol or re-enable stale context attachment.

## 8. Current native implementation

- **Typed-local port:** `read_ids_v1` in [codex-rs/hepta-cognitive-read/src/ids.rs](../../../codex-rs/hepta-cognitive-read/src/ids.rs).
- **Compatibility projection:** `read_v2` in [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs).
- **Authoritative durable cut:** `DurableCognitiveSnapshot`, `lane_c_snapshot`, `revalidate_lane_c_snapshot` and `revalidate_lane_c_cut` in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs).
- **Product consumer:** `read` and `revalidate` in [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs).
- **Final model consumer:** [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs) negotiates the revalidation capability and invokes revalidation before `TurnStart`.
- **Source tests:** [ids_tests.rs](../../../codex-rs/hepta-cognitive-read/src/ids_tests.rs), [v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [tombstone_resurrection_tests.rs](../../../codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs), [lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [cognitive_ranker_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs), and [cognitive_context_budget_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs).
- **Operating reference:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- **Remaining repository evidence:** exact-head and deterministic synthetic-merge execution receipts for the candidate.
- **Remaining external gates:** independent semantic review, target-host qualification, operator acceptance, canary/promotion and release. None is granted by this dossier.
