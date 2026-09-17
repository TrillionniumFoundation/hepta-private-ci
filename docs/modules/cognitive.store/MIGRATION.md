# cognitive.store authoritative-ingress migration and rollback

This runbook closes the repository migration story for the current architecture. The cutover does **not** copy cognitive data into a second database. The durable owner remains the existing Agent-local `cognitive_1.sqlite3`; the migration changes which Rust module product/runtime code is allowed to use to open that owner.

## Invariant

There is exactly one durable cognitive owner per Agent and exactly one product ingress:

```text
agentd / production writer host
        |
        v
codex_hepta_cognitive_store::open_authoritative
        |
        v
hepta-memory::CognitiveStore
        |
        v
cognitive_1.sqlite3
```

`QualificationSemanticStore` and `AdmittedCognitiveStoreV2` are deterministic semantic oracles. They are not synchronized stores, shadow writers, backfill destinations, or fallback databases.

Knowledge facts are not a separately writable second ledger. The durable authority is the immutable memory revision plus its revision-bound `kg_revision_fact_sets` projection. `CognitiveOwnerFrontiers.knowledge_facts` counts those bound fact sets. A projection can be rebuilt from the durable revision/source lineage; it cannot create an independent fact authority.

## Pre-cutover

1. Freeze new cognitive schema changes for the candidate.
2. Record the exact source SHA and candidate tree.
3. Run `python3 scripts/hepta_cognitive_store_authority.py`.
4. Run the focused Rust packages:
   `just test -p codex-hepta-cognitive-store -p codex-hepta-memory -p codex-hepta-agentd`.
5. Verify `codex-hepta-cognitive-store/tests/durable_authority.rs` reopens the same SQLite path and exact recovery anchor.
6. Verify production-writer tests cover restart replay, lifetime single-writer exclusion, crash-after-send indeterminate state, and concurrent dispatch claim serialization.
7. Verify no product opener in `hepta-agentd` contains `CognitiveStore::open(`.
8. Retain a current independently authenticated recovery anchor where the host policy requires rollback detection. The database must never self-authenticate its own backup.

## Cutover

The cutover is source-only because the physical owner and schema do not move.

1. Change product/runtime open calls to `codex_hepta_cognitive_store::open_authoritative`.
2. Keep the durable SQLite engine in `hepta-memory`; do not create or dual-write a new cognitive database.
3. Keep production writer creation behind `ProductionDurableWriter`, its external authority verifier, lifetime OS lock, lease generation, fencing token and durable occurrence journal.
4. Deploy one process generation at a time. A generation change fences the old Agentd before the new runtime is served.
5. Compare the post-restart `CognitiveRecoveryAnchor` with the pre-cutover current anchor when the host has an independent witness.
6. Verify memory, source, tombstone, knowledge-fact and knowledge-graph frontiers from one `lane_c_snapshot` transaction.

There is no count/hash backfill phase in this cutover: the façade opens the same physical database. Creating a second database for a nominal migration would reintroduce the dual-authority problem this change removes.

## Rollback

Rollback changes the caller routing, not the data format.

1. Stop/fence the candidate runtime; do not keep both runtime generations writable.
2. Retain the exact current recovery anchor before changing binaries.
3. Restore the predecessor binary that understands the same SQLite schema.
4. Reopen the same `cognitive_1.sqlite3` only after normal store verification succeeds.
5. If rollback/restore involves a suspect or older database image, do **not** use ordinary `open`. Use exact-current-cut recovery admission. Writable suspect-image recovery currently fails closed until a descriptor-bound writer VFS and an independently current writer fence are implemented.
6. Compare owner/scope frontiers and the independent cut digest before resuming reads or writes.

## Failure rules

- Never fall back from failed recovery admission to ordinary `open`.
- Never copy an old valid SQLite file over the current owner and call that recovery.
- Never run an in-memory V2 store as a production fallback.
- Never dual-write the semantic oracle and SQLite backend.
- Never infer external-effect success from queue admission or process completion.
- Unknown target outcomes remain durable `Indeterminate` and require status/reconciliation.
- A stale writer, stale generation, stale authority receipt, reused intent with drift, broken revision lineage, or tombstone resurrection is terminal for that attempt.

## Writable recovery blocker

`open_with_recovery` intentionally remains fail-closed for writable restoration of a suspect database. The missing primitive is not a SQL query: it is a descriptor-bound SQLite writer connection that cannot reconnect by pathname, plus a current writer fence supplied independently by the host. Implementing a pathname fallback would weaken rollback and TOCTOU guarantees and is prohibited.

The acceptable closure is one of:

1. a qualified descriptor-backed SQLite VFS with retained database/WAL/SHM identities, reconnect disabled, and a current external writer fence; or
2. a separately qualified restore protocol that verifies an exact cold image, restores into a fresh owner under a new fence, atomically publishes the new route/generation, and never mutates the suspect source in place.

Until one is qualified, normal current-owner startup is production-capable, exact-current-cut cold recovery is read-only, and suspect-image writable recovery remains unavailable by design.

## Qualification evidence

Repository completion and release are separate claims. A candidate can set `productionImplementation=true` once the production implementation and named product ingress exist while still keeping `productExecutionProved`, independent acceptance, activation and release false. Exact-head CI, synthetic-merge CI, target-host execution, operator acceptance and release evidence must be attached separately.
