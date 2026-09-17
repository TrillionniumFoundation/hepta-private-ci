# cognitive.store: implementation design

Parent: `docs/modules/cognitive.store/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: one durable SQLite authority with an explicit production façade is implemented on the current candidate; the `hepta-cognitive-store` V1/V2 stores are semantic/conformance models only. Writable corruption recovery and independent acceptance remain separate blockers. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Production/durable roots:

- `codex-rs/hepta-memory`
- `codex-rs/hepta-agentd`

Semantic/conformance root:

- `codex-rs/hepta-cognitive-store`

Packages: `MEM-1-STORE`, `MEM-8-PRODUCTION-WRITER`.

Operation signatures below describe the target contract. Preserve the existing SQLite owner and APIs; do not create another authority or execution spine. `hepta-cognitive-store` may be used as a semantic oracle, but its `BTreeMap` state and image reopen helpers are not product persistence.

## 2. Public operations and contract details

Target semantics remain `append_event(event, expected_frontier, writer_fence) -> EventCommit`; `append_correction(original, successor, fence) -> CorrectionCommit`; `forget(source_scope, frontier, authorization) -> TombstoneCommit`; `open_snapshot(scope, requested_frontier) -> ReadSnapshot`.

The current product open boundary is `codex_hepta_memory::AuthoritativeCognitiveStore`. Agentd runtime startup and the production writer host enter through that façade. Direct construction of `ProductionDurableWriter` remains an internal implementation detail behind the façade; repository `CALLERS.toml` closes the set of allowed production call sites. The qualification-only `AgentdProductionWriterHost::open_with_store` seam has zero allowed product callers.

## 3. State records and transaction design

The durable source of truth is the existing `cognitive_1.sqlite3` database. Memory/source revisions and tombstones are authoritative rows. Knowledge facts are **revision-scoped immutable durable facts attached to an authoritative memory revision**, not an independently writable second ledger: `kg_revision_fact_sets` is keyed by `(memory_id, memory_revision)` and its entity/relation facts are append-only through immutability triggers. `kg_projection*` is a derived generation projection and never becomes source authority.

This resolves the V2 terminology: `MemoryKind::Fact` and `knowledge_fact_frontier` in the in-memory conformance model describe the semantic fact frontier; production durability is represented by the immutable `kg_revision_fact_sets`/entity/relation rows linked to the corresponding memory revision and citations.

Logical owner records therefore remain memory/source revision, immutable revision fact set, correction/successor, tombstone/revocation and projection receipt. Large assets use the existing owner asset store, not inline ledger payloads. One logical write uses one SQLite transaction boundary.

## 4. Deterministic algorithm and scheduling

Authenticate scope and writer; validate referenced assets/source frontiers; perform predecessor CAS; append/canonicalize the existing durable format; commit with the configured SQLite durability profile; only then acknowledge or publish owner-local work. Corrections and logical exclusion append records. Physical erasure/asset removal and derived-artifact revocation remain separate tracked work; a tombstone alone is not full unlearning.

## 5. Capacity and performance profile

Pilot event metadata <= 256 KiB, transaction batch <= 256, bounded snapshot readers and retention per policy. Segment/rotation limits must preserve continuity and acknowledged-history anchors. Measure fsync, WAL/journal growth, reopen, compaction and tombstone traversal at maximum retained size.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before release; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- STORE-01: duplicate same-semantic event returns the prior commit; changed identity content conflicts.
- STORE-02: real SQLite close/reopen preserves the exact current-cut witness and durable rows.
- STORE-03: a second live production writer for the same store fails closed under the OS writer lock/fence.
- STORE-04: restore/recovery never publishes an older cut as current without an independently authenticated witness.
- STORE-05: immutable knowledge-fact rows remain bound to the exact memory revision/citation and projection generations remain rebuildable.
- STORE-06: the H4 persistent prepare/recover harness reopens a new SQLite pool/process generation and replays the same durable occurrence without redispatching an indeterminate effect.

Source tests are identities, not pass receipts until the exact candidate CI completes.

## 7. Integration, migration, rollback and capability ceiling

### Authority cutover

This candidate intentionally performs **no database-format migration**. The existing SQLite store remains the durable authority. Cutover is a call-path change:

1. Agentd runtime opens the SQLite owner through `AuthoritativeCognitiveStore::open`.
2. Production durable writer construction consumes that façade.
3. The in-memory V2 crate is explicitly a conformance model and is never synchronized or dual-written.
4. `CALLERS.toml` prevents a new Agentd product caller from restoring the raw open/writer construction path.

Because the durable schema is unchanged, there is no backfill, copy, dual-write period or fact-frontier reconciliation between two databases. This removes the migration class that would otherwise risk semantic drift.

### Rollback

Rollback of this call-path cutover reverts the façade routing only. It must not restore or rewrite `cognitive_1.sqlite3`, because no data-format transformation occurred. Existing acknowledged SQLite revisions remain the source of truth. Any later schema migration must use the stronger stop/drain/fence/count+digest/reverse-path procedure in `PERSISTENCE.md`.

### Recovery ceiling

Canonical normal open verifies schema/integrity but cannot independently prove rollback/currentness. Authenticated exact-current-cut **read-only** recovery is available. Writable corruption/rollback recovery remains fail-closed because the required descriptor-backed SQLite/VFS connection and independently current writer-fence witness do not yet exist. This candidate does not pretend otherwise.

## 8. Current native implementation

- **Canonical durable authority:** `AuthoritativeCognitiveStore` in [codex-rs/hepta-memory/src/authoritative_store.rs](../../../codex-rs/hepta-memory/src/authoritative_store.rs), wrapping the existing SQLite `CognitiveStore` in [cognitive_store.rs](../../../codex-rs/hepta-memory/src/cognitive_store.rs).
- **Product composition:** Agentd runtime opens through the authoritative façade in [codex-rs/hepta-agentd/src/runtime.rs](../../../codex-rs/hepta-agentd/src/runtime.rs); production writer host does the same in [production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs).
- **Closed-world caller policy:** root [CALLERS.toml](../../../CALLERS.toml) lists the exact production callers and forbids raw `CognitiveStore::open`/direct production writer construction in the Agentd production files.
- **Semantic oracle only:** [codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs) explicitly identifies V1/V2 as in-memory conformance models, not durable production authority.
- **Knowledge facts:** [0003_cognitive_kg_revision_facts.sql](../../../codex-rs/hepta-memory/migrations/0003_cognitive_kg_revision_facts.sql) persists immutable revision-scoped fact sets/entities/relations; [lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs) exposes their fact frontier together with memory/source/tombstone/KG projection frontiers.
- **Recovery:** [cognitive_store_recovery.rs](../../../codex-rs/hepta-memory/src/cognitive_store_recovery.rs) remains fail-closed for writable recovery; [cognitive_store_recovery_read_only.rs](../../../codex-rs/hepta-memory/src/cognitive_store_recovery_read_only.rs) owns authenticated cold-image read-only admission.
- **Durable restart evidence:** the façade unit test performs an actual SQLite close/reopen and exact-cut comparison; the H4 persistent writer example remains the process/power-cycle qualification harness.
- **Remaining source blocker:** descriptor-safe writable recovery/currentness, plus any CI failures on the exact candidate.
- **Remaining external blockers:** independent review/acceptance, target-host durability qualification, promotion and release.
