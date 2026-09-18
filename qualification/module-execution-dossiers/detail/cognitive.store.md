# cognitive.store: implementation design

Parent: `docs/modules/cognitive.store/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: native semantic store, durable SQLite backend and product-facing owner façade are source-implemented on the candidate branch; descriptor-bound writer recovery and independent acceptance remain separate blockers. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-store`.
Packages: `MEM-1-STORE`, `MEM-8-PRODUCTION-WRITER`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. The physical SQLite implementation remains reusable backend code, but product ownership is bound to `codex-hepta-cognitive-store::ProductionCognitiveStore`. Do not create another cognitive authority or a second durable database.

## 2. Public operations and contract details

`append_event(event, expected_frontier, writer_fence) -> EventCommit`; `append_correction(original, successor, fence) -> CorrectionCommit`; `forget(source_scope, frontier, authorization) -> TombstoneCommit`; `open_snapshot(scope, requested_frontier) -> ReadSnapshot`. All authoritative production mutations remain inside one canonical cognitive writer. Retrieval/Neuron/KG do not establish an independent durable writer.

The product-facing production seam is `ProductionCognitiveStore::open` followed by `ProductionCognitiveStore::open_writer`. The latter requires an externally verified `ProductionAuthorityLease` and delegates physical durability to the SQLite backend without exposing that backend as a second product ownership boundary.

## 3. State records and transaction design

Logical owner records: memory event (scope,event ID,revision,source/span references,verification,retention), knowledge fact (fact ID,source support,revision,validity), correction (old/new IDs,reason), tombstone (source range,cutoff,revocation lineage), asset metadata (content digest,media/range,redaction/preprocessor,retention). Index keys include scope+ID+revision and source digest. Large assets use the existing owner asset store, not inline ledger payloads. Append and local publication intent share one durable boundary.

The durable knowledge-fact authority is the SQLite KG revision chain (`kg_revision_fact_sets`, `kg_revision_entities`, `kg_revision_relations` and their immutable citation/count invariants). `MemoryKind::Fact`, `KnowledgeFactRecordV2` and `knowledge_fact_frontier` are semantic/snapshot representations of owner state; they are not a second independently writable fact ledger.

## 4. Deterministic algorithm and scheduling

Authenticate scope and writer; validate referenced assets and source frontiers; perform predecessor CAS; append/canonicalize the existing durable format; fsync before publication acknowledgement; emit outbox updates to projections. Corrections and logical exclusion append records. Physical erasure/asset removal and derived-artifact revocation are separate tracked work; a tombstone alone is not full unlearning.

Production writer acquisition additionally verifies the external grant, Agent owner, grant-bound fence, authority/owner epochs, active lease generation, WAL/FULL durability and the process-lifetime OS writer lock. No dual-write phase is allowed.

## 5. Capacity and performance profile

Pilot event metadata <= 256 KiB, transaction batch <= 256, bounded snapshot readers and retention per policy. Segment/rotation limits must preserve continuity and acknowledged-history anchors. Measure fsync, WAL/journal growth, reopen, compaction and tombstone traversal at maximum retained size.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- STORE-01: duplicate same-semantic event returns the prior commit; changed identity content conflicts.
- STORE-02: durable SQLite mutation survives close/reopen with the same exact logical recovery anchor.
- STORE-03: stale writer and competing writer cannot both advance a frontier; the production writer lifetime lock rejects the second owner.
- STORE-04: crash/unknown external outcome reopens as indeterminate and cannot be redispatched without reconciliation.
- STORE-05: concurrent dispatchers obtain one durable claim and one target invocation.
- STORE-06: restoring or admitting a rollback-sensitive database requires an independently retained exact-current-cut witness; ordinary path reopen is not accepted as descriptor-bound recovery.

The repository already contains native tests for STORE-02 through STORE-05. Exact-candidate CI remains the execution receipt; this document is not itself a pass receipt.

## 7. Integration, cutover and rollback

The convergence is an authority/route cutover over the existing `cognitive_1.sqlite3`, not a copy into a new database. Stop writes, drain local publication work, fence/release the old writer, capture counts/frontiers and an exact recovery anchor, reopen through `ProductionCognitiveStore`, acquire a strictly fresh externally authorized writer generation, verify the pre-cut logical cut, execute one canary mutation and reopen before publishing the new route. There is no dual-write phase.

Rollback similarly stops and reconciles the new writer, terminates its lease, validates binary/schema compatibility and reacquires a fresh rollback generation before reopening the same durable database. Backup restore without an independently current witness is forbidden because it can resurrect deleted or superseded facts.

The detailed sequence is maintained in `docs/modules/cognitive.store/PRODUCTION_CLOSURE.md`.

## 8. Current native implementation

- **Semantic owner:** `CognitiveStore` / `AdmittedCognitiveStoreV2` in [codex-rs/hepta-cognitive-store](../../../codex-rs/hepta-cognitive-store) implement deterministic revision, tombstone, writer-fence, intent/idempotency, integrity and snapshot semantics. V1/V2 remain in-memory semantic oracles and are not themselves the physical database.
- **Product-facing durable owner façade:** `ProductionCognitiveStore` in [codex-rs/hepta-cognitive-store/src/production.rs](../../../codex-rs/hepta-cognitive-store/src/production.rs) is the canonical production composition seam. It owns durable open, recovery-gated open, exact-cut anchor capture and externally authorized writer acquisition while keeping the physical backend private.
- **Physical backend:** `CognitiveStore` in [codex-rs/hepta-memory/src/cognitive_store.rs](../../../codex-rs/hepta-memory/src/cognitive_store.rs) remains the SQLite WAL/FULL durability engine. This is implementation delegation, not a second product authority.
- **Product caller:** `AgentdProductionWriterHost::open` in [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs) now opens through `ProductionCognitiveStore` and acquires its writer there. `open_with_store` remains an explicitly registered H4 qualification boundary with no product callers.
- **Durable reopen evidence:** [codex-rs/hepta-cognitive-store/src/production_tests.rs](../../../codex-rs/hepta-cognitive-store/src/production_tests.rs) mutates the real SQLite store, drops it, reopens through the owner façade and compares exact recovery anchors. [codex-rs/hepta-memory/src/production_writer.rs](../../../codex-rs/hepta-memory/src/production_writer.rs) contains real writer-lock, restart/replay, crash-after-send and concurrent-dispatch tests.
- **Snapshot/parity evidence:** [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs) verifies existing SQLite writes remain readable by the Lane-C snapshot after reopen, including correction/tombstone semantics.
- **Operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) and [docs/modules/cognitive.store/PRODUCTION_CLOSURE.md](../../../docs/modules/cognitive.store/PRODUCTION_CLOSURE.md).
- **Remaining repository blocker:** descriptor-bound writer recovery is still intentionally unavailable in `codex-state`: `open_identity_bound_durable_evidence_pool` fails closed until a qualified descriptor-backed SQLite VFS, non-reconnecting connection and current writer-fence input exist. `ProductionCognitiveStore::open_with_recovery` preserves this fail-closed result and never silently downgrades to ordinary open.
- **Claim boundary:** source/product composition may only be promoted after exact-head plus deterministic merge-candidate CI is green. Descriptor-bound recovery, independent semantic review, target-host qualification, operator acceptance, activation and release remain separate claims and must not be inferred from this source change.
