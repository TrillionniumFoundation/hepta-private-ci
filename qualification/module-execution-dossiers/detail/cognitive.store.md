# cognitive.store: implementation design

Parent: `docs/modules/cognitive.store/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: native semantic store plus existing SQLite owner snapshot integration implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-store`.
Packages: `MEM-1-STORE`, `MEM-8-PRODUCTION-WRITER`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`append_event(event, expected_frontier, writer_fence) -> EventCommit`; `append_correction(original, successor, fence) -> CorrectionCommit`; `forget(source_scope, frontier, authorization) -> TombstoneCommit`; `open_snapshot(scope, requested_frontier) -> ReadSnapshot`. All mutations remain inside the one canonical cognitive writer; retrieval/Neuron/KG send intents rather than opening this writer directly.

## 3. State records and transaction design

Logical owner records: memory event (scope,event ID,revision,source/span references,verification,retention), knowledge fact (fact ID,source support,revision,validity), correction (old/new IDs,reason), tombstone (source range,cutoff,revocation lineage), asset metadata (content digest,media/range,redaction/preprocessor,retention). Index keys include scope+ID+revision and source digest. Large assets use the existing owner asset store, not inline ledger payloads. Append and local publication intent share one durable boundary.

## 4. Deterministic algorithm and scheduling

Authenticate scope and writer; validate referenced assets and source frontiers; perform predecessor CAS; append/canonicalize the existing durable format; fsync before publication acknowledgement; emit outbox updates to projections. Corrections and logical exclusion append records. Physical erasure/asset removal and derived-artifact revocation are separate tracked work; a tombstone alone is not full unlearning.

## 5. Capacity and performance profile

Pilot event metadata <= 256 KiB, transaction batch <= 256, bounded snapshot readers and retention per policy. Segment/rotation limits must preserve continuity and acknowledged-history anchors. Measure fsync, WAL/journal growth, reopen, compaction and tombstone traversal at maximum retained size.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- STORE-01: duplicate same-semantic event returns the prior commit; changed identity content conflicts.
- STORE-02: crash before/after sync and acknowledgement loss preserve anchored history.
- STORE-03: stale writer and competing writer cannot both advance a frontier.
- STORE-04: restoring a backup before a forget cutoff replays revocations before any read becomes visible.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 uses a real store/open_snapshot consumer with exact physical format and file/DB path receipts. HNMF engrams and KG remain projections. Rollback must validate current tombstone frontier and compatible readers; it must not revive earlier acknowledged deleted content.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `AdmittedCognitiveStoreV2` and the canonical durable façade in [codex-rs/hepta-cognitive-store](../../../codex-rs/hepta-cognitive-store/src/lib.rs); physical `CognitiveStore` and `open_with_recovery` in [hepta-memory](../../../codex-rs/hepta-memory/src/cognitive_store.rs); whole-cut and proof-bound `lane_c_snapshot_page` reads in [lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs); named product composition in [AgentdProductionWriterHost](../../../codex-rs/hepta-agentd/src/production_writer_host.rs).
- **State and recovery:** V1/V2 remain semantic in-memory components, while `hepta-memory::CognitiveStore` over `cognitive_1.sqlite3` is the only physical owner. Writable recovery is source-implemented by retaining source descriptors, fencing ordinary handles, materializing a bounded private database/WAL/journal copy, comparing the independent exact-current-cut anchor, verifying SQLite integrity and production authority/fence, checkpointing, and atomically publishing the recovered generation. Ordinary `open` still does not authenticate currentness.
- **Bounded reads:** the original whole-scope adapter retains its 16,384-revision pilot bound. `lane_c_snapshot_page` keyset-pages at most 512 heads and reconstructs complete ancestry/citations for only those heads; its cursor binds all owner frontiers, citation count, the complete ordered head set and observation time so an intervening correction, deletion, source/fact/KG change or validity-time change rejects continuation.
- **Source tests:** [v2_tests.rs](../../../codex-rs/hepta-cognitive-store/src/v2_tests.rs), [lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [cognitive_store_recovery_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs), and [cognitive_store_product_writer.rs](../../../codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs). These are test identities; exact-candidate CI receipts determine pass/fail.
- **Performance evidence path:** [cognitive_store_perf.rs](../../../codex-rs/hepta-memory/examples/cognitive_store_perf.rs) emits `PERF-DURABLE` JSON; consolidated source CI requests both 256-record and 16,384-record profiles when this durable boundary changes.
- **Remaining work/external gates:** do not create another memory database. The host must independently retain/authenticate the current-cut witness and verify production authority. Exact-head/merge receipts, target-host measurements, independent semantic review, operator acceptance, activation, canary, promotion and release remain separate evidence gates; physical erasure/model unlearning remains separate from a tombstone.
