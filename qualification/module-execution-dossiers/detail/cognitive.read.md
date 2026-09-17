# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded V2 read projection, canonical SQLite-cut consumer and native model-context product composition implemented. The final native model dispatch now reacquires the same owner read and rejects snapshot/read/projection drift before `dispatch_native` and `TurnStart`. Exact-candidate execution evidence, independent acceptance, activation and release remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-read`.
Packages: `MEM-READ-1-SNAPSHOT-PORT`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining qualification; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`acquire_snapshot(scope, source_frontiers, generations) -> SnapshotReadPort`; `read_ids(snapshot, ids, fields) -> BoundedReadResult`; `revalidate(packet, current_revocation_frontier) -> ValidatedAttachment | Stale`. No mutation/SQL-writer handle is exposed. Cross-owner reads bind a coherent declared cut and report missing/lagging owners explicitly.

The synchronous `AuthoritativeCognitiveSnapshotProvider`/`read_authoritative` harness in `hepta-cognitive-read` is retained only as a hidden compatibility and deterministic contract-test surface. Production acquisition is the async canonical SQLite-owner path in `hepta-memory` through `CognitiveStore::lane_c_snapshot` / `DurableCognitiveSnapshot`; there is no second production snapshot provider.

## 3. State records and transaction design

No authoritative domain facts. Cache keys include principal/purpose, source/event revisions, tombstone frontier, KG/engram generation, encoder/preprocessor identity and requested fields. Cache values are bounded redacted projections. A read snapshot holds leases/pins on actual source generations and releases them on completion/cancellation.

The current SQLite adapter returns a historical cut rather than a write-blocking lease. Product consumers therefore retain the returned `snapshot_digest` and `read_digest` and re-read the owner immediately before the downstream model-dispatch boundary. The final-use check also binds selected item revisions/content and the evaluated context-plan digest/decision; a fresh request-local planning receipt timestamp may differ.

## 4. Deterministic algorithm and scheduling

Authenticate purpose and scope before lookup; acquire the declared coherent source cut; fetch exact revisions; apply redaction and current revocation; return bounded facts with provenance. Before physical model-request attachment, revalidate the packet against one current compatible snapshot. Do not combine source rows from different frontiers because each individual read succeeded.

For the current native product path, Agentd first revalidates its SQLite cut before publishing `CognitiveContextSnapshot`. The infer worker preserves the original query and returned snapshot/read receipts while opening the App Server thread. Immediately before durable provider dispatch it calls Agentd for the same bounded context again. A changed `snapshot_digest`, `read_digest`, omitted count, selected item set/revisions/content, evaluated-context digest or read/abstain decision aborts while the inference journal is still `Reserved`; `turn/start` is not sent. Ranker unavailability/revocation also fails the second read closed. This is a final-use observation, not an atomic lease against a write occurring after that check.

## 5. Capacity and performance profile

Pilot read <= 512 IDs and <= 1 MiB encoded result subject to context limits; snapshot lifetime <= the request deadline; cache bytes and pins are host-profile ceilings. A slow reader must expire or receive unavailable rather than hold unbounded history.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- READ-01: a packet becomes stale when one selected source revision or tombstone frontier changes.
- READ-02: cross-principal cache lookup is rejected even for equal query text.
- READ-03: cancellation releases read pins/descriptors without granting write access.
- READ-04: incomplete projection generation is reported unavailable, never presented as a complete snapshot.
- READ-05: after Agentd returns a valid context, a correction/tombstone before native model dispatch changes the owner snapshot/read receipts and the final-use gate rejects the old attachment before `dispatch_native`/`TurnStart`.

READ-01 through READ-04 remain required product designs where a concrete owner has not supplied execution evidence. READ-05 has repository regression sources in `hepta-agentd/src/cognitive_finalization_tests.rs` and `hepta-infer-worker-host/src/native_app_server_tests.rs`; their presence is not an exact-candidate pass receipt.

## 7. Integration, rollback and capability ceiling

Implement the source-store reader adapter and fixture port against identical contracts. The no-owned-state test is required. Rollback invalidates incompatible cache/snapshot generations; cached reads cannot suppress immediate revocation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `read_v2` in [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs); `DurableCognitiveSnapshot` in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs). Bounded V2 read projection and existing SQLite-cut consumer are implemented.
- **Production composition:** [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs) acquires and revalidates the canonical owner cut, and [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs) consumes the returned context as untrusted model context. It performs a second owner read at the final-use boundary and verifies `snapshot_digest`, `read_digest`, selected projection and stable plan decision before journaling provider dispatch.
- **Provider convergence:** the synchronous `AuthoritativeCognitiveSnapshotProvider` harness is not the production owner. It remains hidden for deterministic contract tests and compatibility. Production freshness is owned by the async `DurableCognitiveSnapshot` SQLite path, so the product does not maintain two peer provider authorities.
- **State and recovery:** `read_v2` reuses V1 selection, adds request-bound canonical bytes, sorts citations and accounts for byte-limit omissions. `DurableCognitiveSnapshot` reads an owner-acquired SQLite cut; native bytes are not an admitted ModulePort/wire protocol.
- **Source tests:** [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs](../../../codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [codex-rs/hepta-agentd/src/cognitive_finalization_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_finalization_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) and [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work:** run the exact-head and deterministic synthetic-merge candidate gates; obtain independent semantic review and target-host/product execution qualification. A successful final-use revalidation is still an observation immediately before dispatch, not a lease that prevents a subsequent concurrent owner write.
