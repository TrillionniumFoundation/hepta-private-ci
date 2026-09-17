# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded V2 read projection, canonical SQLite-cut consumer, Agentd product caller and final model-attachment refresh are implemented; exact-candidate qualification and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-read`.
Packages: `MEM-READ-1-SNAPSHOT-PORT`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining qualification; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`acquire_snapshot(scope, source_frontiers, generations) -> SnapshotReadPort`; `read_ids(snapshot, ids, fields) -> BoundedReadResult`; `revalidate(packet, current_revocation_frontier) -> ValidatedAttachment | Stale`. No mutation/SQL-writer handle is exposed. Cross-owner reads bind a coherent declared cut and report missing/lagging owners explicitly.

## 3. State records and transaction design

No authoritative domain facts. Cache keys include principal/purpose, source/event revisions, tombstone frontier, KG/engram generation, encoder/preprocessor identity and requested fields. Cache values are bounded redacted projections. A read snapshot holds leases/pins on actual source generations and releases them on completion/cancellation.

The current SQLite product path deliberately does not manufacture the complete cross-owner `LaneCGenerationVectorV1`: the memory owner only controls the cognitive-owned frontiers. `DurableCognitiveSnapshot::read_current` constructs the exact snapshot-bound V2 request from the owner cut, and `CognitiveStore::revalidate_lane_c_read` binds the returned read receipt back to that cut before Agentd publishes it. The host-composed `AuthoritativeCognitiveSnapshotProvider` contract remains available only where the caller genuinely owns every external generation-vector input.

## 4. Deterministic algorithm and scheduling

Authenticate purpose and scope before lookup; acquire the declared coherent source cut; fetch exact revisions; apply redaction and current revocation; return bounded facts with provenance. Before physical model-request attachment, revalidate the packet against one current compatible snapshot. Do not combine source rows from different frontiers because each individual read succeeded.

The native App Server worker now performs a second generation/lifecycle-fenced `CognitiveContext` read after `thread/start` and immediately before durable dispatch plus `turn/start`. It compares snapshot digest, read receipt digest, omitted count, admitted items and stable planner semantics. Any correction, deletion, tombstone, validity change, ranker reorder/revocation or read/abstain drift rejects the turn before dispatch. The refreshed snapshot, not the historical first read, is serialized into model additional context. This is a final-use check, not an atomic lease over writes that occur after the check.

## 5. Capacity and performance profile

Pilot read <= 512 IDs and <= 1 MiB encoded result subject to context limits; snapshot lifetime <= the request deadline; cache bytes and pins are host-profile ceilings. A slow reader must expire or receive unavailable rather than hold unbounded history.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

The current Agentd product consumer admits at most 1024 V2 records / 1 MiB, returns at most four context items under a 24 KiB response envelope, and the worker enforces an 8 KiB model-attachment envelope. Final-use refresh repeats the bounded owner read once for context-bearing turns.

## 6. Concrete verification cases

- READ-01: a packet becomes stale when one selected source revision or tombstone frontier changes.
- READ-02: cross-principal cache lookup is rejected even for equal query text.
- READ-03: cancellation releases read pins/descriptors without granting write access.
- READ-04: incomplete projection generation is reported unavailable, never presented as a complete snapshot.
- READ-05: after the first Agentd context read, a correction/tombstone or changed read receipt causes final model attachment to fail before durable dispatch/`turn/start`.
- READ-06: a refreshed planner receipt may replace the earlier short-lived receipt only when snapshot/read digests, admitted items and stable planner semantics are unchanged.

These are required product test designs. Native regression identities include `codex-rs/hepta-agentd/src/cognitive_context_tests.rs` and `codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs`; exact candidate CI remains the execution receipt.

## 7. Integration, rollback and capability ceiling

Implement the source-store reader adapter and fixture port against identical contracts. The no-owned-state test is required. Rollback invalidates incompatible cache/snapshot generations; cached reads cannot suppress immediate revocation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `read_v2` in [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs); `DurableCognitiveSnapshot` in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs). Bounded V2 read projection and existing SQLite-cut consumer are implemented.
- **Production composition:** `codex-rs/hepta-agentd/src/cognitive_context.rs` consumes the owner-built `read_current` seam and binds exact revision/content matches; `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` performs final-use refresh and attaches only the refreshed context as untrusted model input. `docs/modules/cognitive.read/IMPLEMENTATION_MAP.json` binds these claims to exact current Git blob identities.
- **State and recovery:** `read_v2` reuses V1 selection, adds request-bound canonical bytes, sorts citations and accounts for byte-limit omissions. `DurableCognitiveSnapshot` reads an owner-acquired SQLite cut; native bytes are not an admitted ModulePort/wire protocol. `revalidate_lane_c_read` rejects a receipt from another snapshot and reacquires the complete cut before publication.
- **Authority boundary:** the SQLite product path is the canonical durable owner seam. `AuthoritativeCognitiveSnapshotProvider` is not silently treated as the SQLite provider because its complete generation vector contains model/tokenizer/template/tool and other values owned outside memory; host composition must supply those values truthfully before using that contract.
- **Source tests:** [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs](../../../codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), and [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) and [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining repository work:** execute exact-head and deterministic synthetic-merge CI for this candidate and keep blob-bound caller evidence current. No repository-controlled caller-composition gap remains for the native Agentd/App Server path.
- **Remaining external gates:** independent semantic review, target-host/product execution qualification, operator acceptance, promotion and release remain separate and are not inferred from source composition.
