# cognitive.store: implementation design

Parent: `docs/modules/cognitive.store/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: the in-memory semantic store, the existing SQLite authoritative owner, durable provisional/verified/tombstone admission, exact-cut whole-history paging, and the named Agentd product read path are source-implemented. Production write composition, descriptor-safe writable recovery, physical archive/pruning retention, target-host performance qualification and independent acceptance remain separate gaps. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Declared primary root: `codex-rs/hepta-cognitive-store`.
Durable implementation package already Cargo-bound to this module: `codex-rs/hepta-memory`.
Packages: `MEM-1-STORE`, `MEM-8-PRODUCTION-WRITER`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve the existing SQLite owner and APIs; do not create another authority, memory database or execution spine.

## 2. Public operations and contract details

`append_event(event, expected_frontier, writer_fence) -> EventCommit`; `append_correction(original, successor, fence) -> CorrectionCommit`; `forget(source_scope, frontier, authorization) -> TombstoneCommit`; `open_snapshot(scope, requested_frontier) -> ReadSnapshot`. All mutations remain inside the one canonical cognitive writer; retrieval/Neuron/KG send intents rather than opening this writer directly.

The source tree currently realizes these semantics through two layers: `hepta-cognitive-store` is the authority-free semantic oracle/types surface, while `hepta-memory::CognitiveStore` is the physical SQLite owner. `memory_admission.rs` persists model/compaction candidates as provisional memories, requires an explicit content-bound evidence digest plus CAS before verification, and routes deletion through the existing append-only tombstone path. This split must converge by typed adapter/ownership declaration rather than by introducing a second durable writer.

## 3. State records and transaction design

Logical owner records: memory event (scope,event ID,revision,source/span references,verification,retention), knowledge fact (fact ID,source support,revision,validity), correction (old/new IDs,reason), tombstone (source range,cutoff,revocation lineage), asset metadata (content digest,media/range,redaction/preprocessor,retention). Index keys include scope+ID+revision and source digest. Large assets use the existing owner asset store, not inline ledger payloads. Append and local publication intent share one durable boundary.

The physical owner stores immutable source and memory revisions, heads, citations, structured fact sets, KG projection receipts and deletion lineage in `cognitive_1.sqlite3`. `remember_with_kg`, `correct_with_kg` and `forget_with_kg` update the cited source, memory revision, structured facts and complete projection inside one SQLite transaction. The V2 semantic store never replaces that owner.

## 4. Deterministic algorithm and scheduling

Authenticate scope and writer; validate referenced assets and source frontiers; perform predecessor CAS; append/canonicalize the existing durable format; commit the durable transaction before publication acknowledgement; emit or reconcile bounded publication state through the existing owner paths. Corrections and logical exclusion append records. Physical erasure/asset removal and derived-artifact revocation are separate tracked work; a tombstone alone is not full unlearning.

The hardened V2 semantic boundary rejects contradicted candidates and rejects an unverified inference before it can become a live `Fact`. It reserves record and idempotency-journal capacity for terminal tombstones, bounds ordinary retry journal growth, and cross-validates receipt identity, record binding, store frontiers and final snapshot state on image export/reopen. These checks are semantic-oracle invariants; durable product behavior remains owned by the SQLite writer.

## 5. Capacity and performance profile

Pilot event metadata <= 256 KiB, transaction batch <= 256, bounded snapshot readers and retention per policy. Segment/rotation limits must preserve continuity and acknowledged-history anchors. The existing full Lane-C snapshot remains bounded to 16,384 immutable revisions, 65,536 citations and 65,536 source rows in one exact scope.

`CognitiveStore::lane_c_lineage_page` is the source-implemented long-history traversal path. It pages only whole memory histories, never splits one predecessor chain across pages, carries global owner/tombstone frontiers, binds consecutive pages to an exact logical owner-state digest and fails if the owner mutates between page acquisitions. One page is bounded to 256 memory identities and 4,096 revisions. This closes the bounded traversal gap; it does not authorize physical pruning or archive deletion. Removing authoritative rows still requires a durable predecessor anchor and deletion-frontier continuity format.

`codex-rs/hepta-memory/examples/cognitive_store_perf.rs` is the executable PERF-DURABLE measurement source. It exercises real durable writes, SQLite-family byte growth, owner snapshot materialization, reopen and exact-cut revalidation and emits machine-readable measurements. Checked-in source is not a target-host measurement receipt; retain exact source/binary/host identity with every run.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before changing performance or activation claims.

## 6. Concrete verification cases

- STORE-01: duplicate same-semantic event returns the prior commit; changed identity content conflicts.
- STORE-02: crash before/after sync and acknowledgement loss preserve anchored history.
- STORE-03: stale writer and competing writer cannot both advance a frontier.
- STORE-04: restoring a backup before a forget cutoff replays revocations before any read becomes visible.
- STORE-05: unverified inference and contradicted candidate cannot become a live fact/record.
- STORE-06: ordinary record or retry-journal saturation cannot block a terminal forget.
- STORE-07: a checksum-valid image with receipt/record/frontier cross-link drift is rejected on reopen.
- STORE-08: each lineage page is bound to one exact owner cut, carries the global tombstone frontier, contains complete per-memory ancestry and rejects a stale cursor after an owner mutation.

These are required product test designs unless a current exact-candidate receipt proves the named source test. A source file or historical workflow run is not itself a pass receipt.

## 7. Integration, rollback and capability ceiling

The read side already has a named product composition: `codex-rs/hepta-agentd/src/cognitive_context.rs` acquires the real `lane_c_snapshot`, executes the bounded cognitive read port, intersects it with the existing SQLite retrieval provider, exact-matches record ID/revision/content digest, and revalidates the owner cut before publication. `AgentdClient::cognitive_context` is consumed by `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` before actual App Server model execution. This is source-level I3 read composition, not independent target-host acceptance.

The write side remains narrower. The real App Server cognitive product E2E exercises remember/correct/forget only under the explicit `qualification-cognitive-write` profile, and the local memory saga explicitly denies production-caller authority. Do not relabel those paths as an activated production writer. A production write adapter must reuse the existing SQLite writer plus externally verified authority/fence; it must not route durable facts through the in-memory V2 store.

The semantic/durable write contracts are not yet identical: V2 distinguishes `Episode`, `Fact`, `Preference` and `Procedure`, while the current durable `memory_revisions` schema does not persist that kind and the Lane-C owner projection currently exposes eligible durable memories as `Fact`. Production write convergence therefore requires an explicit compatible schema/contract decision, global snapshot CAS in the same durable mutation, and a durable intent-identity journal. The recovery schema oracle must be regenerated and independently verified with any schema migration.

Rollback must validate the current tombstone frontier and compatible readers; it must not revive earlier acknowledged deleted content. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented semantic entrypoints:** `CognitiveStore` / hardened `AdmittedCognitiveStoreV2` in [codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs). These are in-memory semantic components and are not the physical database.
- **Implemented durable owner:** `CognitiveStore` in [codex-rs/hepta-memory/src/cognitive_store.rs](../../../codex-rs/hepta-memory/src/cognitive_store.rs), durable memory/KG writes in [cognitive_intelligence_writer.rs](../../../codex-rs/hepta-memory/src/cognitive_intelligence_writer.rs), and provisional/verified/tombstone admission in [memory_admission.rs](../../../codex-rs/hepta-memory/src/memory_admission.rs).
- **Implemented read provider:** `lane_c_snapshot` plus revalidation in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs). It reads one authorized SQLite transaction and compares exact cuts including corrections/tombstones.
- **Implemented lineage pager:** [codex-rs/hepta-memory/src/lane_c_paging.rs](../../../codex-rs/hepta-memory/src/lane_c_paging.rs), with real SQLite tests in [codex-rs/hepta-memory/tests/lane_c_paging.rs](../../../codex-rs/hepta-memory/tests/lane_c_paging.rs).
- **Named product read caller:** [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs), consumed by [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs).
- **Source tests:** [codex-rs/hepta-cognitive-store/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-store/src/v2_tests.rs), [codex-rs/hepta-cognitive-store/src/hardening_tests.rs](../../../codex-rs/hepta-cognitive-store/src/hardening_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [codex-rs/hepta-memory/tests/lane_c_paging.rs](../../../codex-rs/hepta-memory/tests/lane_c_paging.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), and [codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs). These are source identities, not a claim that the current PR candidate has passed them.
- **Operating reference:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- **Performance source:** [codex-rs/hepta-memory/examples/cognitive_store_perf.rs](../../../codex-rs/hepta-memory/examples/cognitive_store_perf.rs).
- **Recovery blocker:** the retained recovery guard can bind DB/WAL/SHM identities and compare an independently retained exact logical cut, but writable `open_with_recovery` still lacks a descriptor-backed SQLite VFS/equivalent, current writer-fence input and reconnect-proof ownership. It must remain fail-closed; ordinary reopen plus cut comparison is not full recovery admission.
- **Remaining repository work:** physical archive/pruning retention with durable predecessor/deletion anchors; V2/durable write-contract convergence; authenticated production memory writes; descriptor-safe writable recovery; target-host PERF-DURABLE execution; exact-head/synthetic-merge and independent acceptance evidence.
