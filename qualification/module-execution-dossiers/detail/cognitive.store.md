# cognitive.store: implementation design

Parent: `docs/modules/cognitive.store/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: native semantic store, compile-time durable-owner binding, existing SQLite authoritative writer/snapshot integration and explicit Agentd production-writer host are implemented. Default activation, descriptor-backed writer recovery, target-host performance receipts and independent acceptance remain separate; see section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

Pilot event metadata <= 256 KiB and transaction batch <= 256 remain target ceilings. V2 additionally hard-bounds record revisions, reserves revision/journal capacity for revocation, hard-bounds the intent journal and exposes ledger-root-bound pages of at most 4,096 records. The SQLite owner contains an ignored PERF-DURABLE harness that can populate up to 16,384 retained revisions and emit commit p50/p95/p99, WAL/checkpoint, database-size, maximum-cut, reopen and revalidation measurements. The harness is measurement machinery, not a target-host receipt until executed on the selected host. Physical archive/retention that actually removes authoritative history remains separate because it must preserve ancestry, tombstone frontiers and retired intent identity.

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

- **Implemented entrypoints:** `AdmittedCognitiveStoreV2` and `AuthoritativeCognitiveStoreOwnerV1` in [codex-rs/hepta-cognitive-store](../../../codex-rs/hepta-cognitive-store/src/lib.rs); physical `CognitiveStore` in [codex-rs/hepta-memory/src/cognitive_store.rs](../../../codex-rs/hepta-memory/src/cognitive_store.rs); `ProductionDurableWriter` in [codex-rs/hepta-memory/src/production_writer.rs](../../../codex-rs/hepta-memory/src/production_writer.rs); `lane_c_snapshot` in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs); and the named product host `AgentdProductionWriterHost` in [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs).
- **Admission and bounds:** V2 accepts only `Verified` candidates into the live semantic ledger, reserves mutation/journal capacity for revocation, validates image sequence/frontiers/receipt-to-record relationships, and exposes mutation-fenced ledger-root paging. The durable owner separately persists unverified model/compaction candidates as `Provisional` and requires explicit content-bound verification before facts can be admitted.
- **State and recovery:** the real durable owner remains `hepta-memory::CognitiveStore` and `cognitive_1.sqlite3`; it now implements the semantic crate's compile-time authoritative-owner descriptor. `ProductionDurableWriter` requires an external verified lease, grant-bound fencing token, WAL/FULL, CAS and a process-lifetime writer lock. Descriptor-safe read-only current-cut recovery exists. `open_with_recovery_writer` additionally requires a current host writer fence before any writer-open attempt, but the descriptor-backed non-reconnecting writer backend is still unavailable and therefore fails closed.
- **Product composition:** root `CALLERS.toml` binds `ProductionDurableWriter::open` to `hepta-agentd/src/production_writer_host.rs`; Agentd's cognitive read path is consumed by the native inference host. These are named source callsites, not default activation or target-host execution receipts.
- **Source tests:** [codex-rs/hepta-cognitive-store/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-store/src/v2_tests.rs), [codex-rs/hepta-memory/src/cognitive_store_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_tests.rs), [codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), and [codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs). These remain test identities until exact-candidate execution evidence exists.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- **Remaining work:** do not create another memory database or downgrade recovery to a path reopen. Implement the qualified descriptor-backed SQLite writer backend consumed by `open_with_recovery_writer`; execute the PERF-DURABLE profile on the selected host; design physical archive/retention with ancestry/tombstone/retired-intent proofs; then obtain exact-candidate, independent acceptance and activation receipts.
