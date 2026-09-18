# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: authoritative typed read, immutable SQLite owner cut, and `hepta-agentd` product source composition implemented; exact-candidate qualification, independent acceptance, promotion and release remain separate evidence gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-read`.
Packages: `MEM-READ-1-SNAPSHOT-PORT`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and current product composition. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`acquire_snapshot(scope, source_frontiers, generations) -> SnapshotReadPort`; `read_ids(snapshot, ids, fields) -> BoundedReadResult`; `revalidate(packet, current_revocation_frontier) -> ValidatedAttachment | Stale`. No mutation/SQL-writer handle is exposed. Cross-owner reads bind a coherent declared cut and report missing/lagging owners explicitly.

The current Rust realization separates two layers deliberately. `read_v2` is a lower-level projection primitive over caller-supplied immutable snapshot bytes. Product callers use `read_authoritative`, which acquires the snapshot from an `AuthoritativeCognitiveSnapshotProvider`, binds scope/purpose, authority epoch, owner frontiers, host generation/profile identities, lease and receipt digests, and returns an `AuthoritativeReadGuardV1`. That guard must reacquire the current provider immediately before downstream use and rejects provider, vector or snapshot drift.

## 3. State records and transaction design

No authoritative domain facts are written by this module. `CognitiveStore::lane_c_snapshot` reads all Lane-C owner facts needed for one cut in one SQLite read transaction and materializes an owned immutable `DurableCognitiveSnapshot`. The production provider owns that cut; there is no moving `visible()`/`fetch()` view whose methods can observe different current states.

Cache/snapshot identities include principal/purpose, memory/source/tombstone/knowledge frontiers, KG generation, encoder/retrieval profile, optional selected model digest, authority epoch and the explicit identities for host dimensions not consumed by this path. A read snapshot has a bounded lease. Reacquisition, not a caller assertion, establishes that the same provider/vector/snapshot is still current before delivery.

## 4. Deterministic algorithm and scheduling

Authenticate purpose and scope before lookup; acquire one owner-defined frozen source cut; construct the host-frozen `LaneCGenerationVectorV1`; call `read_authoritative`; fetch content only for exact revision/content digests admitted by that guard; perform bounded optional ranking and context planning; reacquire a new SQLite cut; rebuild the same host vector; call `AuthoritativeReadGuardV1::revalidate`; then independently revalidate optional ranker registry currentness. `hepta-agentd::state_control` passes the exact refreshed `current_generation` as the authority epoch, refreshes fleet lifecycle again after the async read, requires Running+Ready, and rejects any generation change before the response is emitted.

Do not combine source rows from different frontiers because each individual read succeeded. Do not attach a result after its acquisition deadline or lease expiry.

## 5. Capacity and performance profile

Pilot read <= 512 IDs and <= 1 MiB encoded result subject to context limits; snapshot lifetime <= the request deadline; cache bytes and pins are host-profile ceilings. The current Agentd context caller is stricter: it limits the downstream context response to 24 KiB and the authoritative context lease/deadline to one second. A slow reader expires or receives a fail-closed error rather than holding unbounded history.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before broader composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- READ-01: a packet becomes stale when one selected source revision, snapshot digest or generation vector changes.
- READ-02: cross-principal/scope acquisition is rejected even for equal query text.
- READ-03: authority-epoch drift, provider drift, deadline expiry or lease expiry rejects before final use.
- READ-04: incomplete or changed owner projection is unavailable/stale, never presented as a complete current snapshot.
- READ-05: lower-level caller-supplied snapshot projection cannot be mistaken for the product authoritative guarantee; product code calls `read_authoritative`.

These cases have focused source tests where named in section 8. Exact-candidate CI/qualification receipts remain separate from test source identity.

## 7. Integration, rollback and capability ceiling

The production read adapter is `codex-rs/hepta-agentd/src/cognitive_context.rs`. It composes the existing SQLite owner with `AuthoritativeCognitiveSnapshotProvider`; it does not add a writer. `read_v2` remains available for owner-internal/unit-level projection but is documented as a lower-level primitive and is not the Agentd product entry path.

Rollback invalidates incompatible host/vector/snapshot generations; cached reads cannot suppress immediate revocation. Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots because final use requires provider reacquisition plus the Agentd lifecycle fence. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `read_authoritative` in [codex-rs/hepta-cognitive-read/src/authoritative.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative.rs); `read_v2` in [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs); `DurableCognitiveSnapshot` in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs); `AgentdAuthoritativeSnapshotProvider` in [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs).
- **Product caller:** `hepta-agentd` cognitive context now acquires a real SQLite owner cut, binds a full host generation vector, calls `read_authoritative`, uses the authoritative binding digest in context planning, reacquires the current cut before delivery, and invokes `AuthoritativeReadGuardV1::revalidate`. The surrounding Agentd state-control path passes its exact refreshed `current_generation` into the read, refreshes again after the async boundary, rechecks Running+Ready and requires that generation to remain exactly equal to the epoch bound by the read.
- **State and recovery:** `read_v2` remains a deterministic lower-level projection. `AuthoritativeReadGuardV1` owns the acquisition request, authoritative snapshot receipt and bound result so final-use revalidation is part of the product contract. `DurableCognitiveSnapshot` is an owned immutable single-transaction cut, not a moving adapter view. Native bytes are not an admitted ModulePort/wire protocol.
- **Source tests:** [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [codex-rs/hepta-cognitive-read/src/authoritative_tests.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs), [codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs](../../../codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs), and [codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs). Provider-level cases prove exact generation/epoch/provider/lease rejection; the budget-test race executes the full production `read()` path, blocks after authoritative acquisition, advances a real SQLite memory revision, and requires the final-use fence to fail closed before context delivery. The ranker-gated control-path race advances Fleet lifecycle from Running to Draining while the request is in flight and requires the outer state-control authority fence to reject before payload delivery.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) and [docs/modules/cognitive.read/TECHNICAL.md](../../../docs/modules/cognitive.read/TECHNICAL.md).
- **Repository-controlled closure:** exact revision/snapshot revalidation and broader provider/vector/authority/lease revalidation are source-composed. The remaining gates are exact-candidate execution evidence, independent semantic/target-host qualification, operator acceptance, promotion and release. Those gates must not be inferred from this source change.
