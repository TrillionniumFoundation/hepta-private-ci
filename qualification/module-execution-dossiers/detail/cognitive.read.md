# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded V2 read projection, durable SQLite-cut consumer, Agentd owner-side receipt finalization, and native-host pre-`TurnStart` composition are implemented in source; exact-candidate independent qualification and the wider transport race fixture remain open. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-read`.
Packages: `MEM-READ-1-SNAPSHOT-PORT`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset, product callers and remaining qualification work; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`acquire_snapshot(scope, source_frontiers, generations) -> SnapshotReadPort`; `read_ids(snapshot, ids, fields) -> BoundedReadResult`; `revalidate(packet, current_revocation_frontier) -> ValidatedAttachment | Stale`; `finalize_context_receipt(snapshot_digest, read_digest) -> Current | Stale`. No mutation/SQL-writer handle is exposed. Cross-owner reads bind a coherent declared cut and report missing/lagging owners explicitly. Finalization is an owner-side compare-and-validate observation and never a bearer grant or future-write lease.

## 3. State records and transaction design

No authoritative domain facts. Cache keys include principal/purpose, source/event revisions, tombstone frontier, KG/engram generation, encoder/preprocessor identity and requested fields. Cache values are bounded redacted projections. A durable Lane C read snapshot is one coherent owner transaction cut and releases transaction resources after materialization; current production code does not claim a retained source-generation lease after that cut is returned.

## 4. Deterministic algorithm and scheduling

Authenticate purpose and scope before lookup; acquire the declared coherent source cut; fetch exact revisions; apply redaction and current revocation; return bounded facts with provenance. Agentd intersects retrieval content only when exact record ID, revision and content digest are present in the bounded read, then revalidates the cut before publishing the cognitive-context response.

For model execution, retain the returned `snapshot_digest` and `read_digest`. After the native host has established the exact App Server thread and rechecked Agent lifecycle generation, it synchronously journals the exact thread/provider/context dispatch intent before any external model turn can be submitted. It then calls the owner-side finalizer immediately before `TurnStart`. The owner reacquires the canonical private Lane C cut, exact-compares the snapshot digest, reruns the same bounded V2 projection, exact-compares the read receipt digest, and revalidates the cut again. A correction, delete/tombstone, validity change, citation/frontier change or owner conflict observed before finalization fails closed. If finalization or cancellation fails after the synced dispatch intent but before `TurnStart`, the durable control records a proven pre-turn stop and releases the local slot; no provider turn is sent. Do not combine source rows from different frontiers because each individual read succeeded. Finalization does not prevent a write after it returns.

## 5. Capacity and performance profile

Pilot read <= 512 IDs and <= 1 MiB encoded result subject to context limits; snapshot lifetime <= the request deadline; cache bytes and pins are host-profile ceilings. The current product adapter uses the stricter native limits documented by the owner: V2 read <= 1 MiB, Agentd cognitive-context JSON <= 24 KiB, and model additional-context attachment <= 8 KiB. A slow reader must expire or receive unavailable rather than hold unbounded history.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before qualification; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- READ-01: a packet becomes stale when one selected source revision or tombstone frontier changes.
- READ-02: cross-principal cache lookup is rejected even for equal query text.
- READ-03: cancellation releases read pins/descriptors without granting write access.
- READ-04: incomplete projection generation is reported unavailable, never presented as a complete snapshot.
- READ-05: `CognitiveContext` succeeds, the selected memory is then corrected/tombstoned, and `finalize_context_receipt` rejects the old `snapshot_digest/read_digest` before model dispatch.
- READ-06: the Agentd finalize request/response round trip is bounded and identity/generation fenced; a mismatched echoed receipt is rejected by the client.
- READ-07: a synced native dispatch intent can be durably stopped before `TurnStart`, releasing the slot without fabricating provider terminality or usage.
- READ-08: a transport-level fixture drives `CognitiveContext -> owner mutation -> CognitiveContextFinalize -> no TurnStart` across Agentd and the native App Server boundary.

READ-01 through READ-07 have native source tests or implementation fixtures in the current tree; they are still test identities rather than exact-candidate pass receipts for this documentation revision. READ-08 remains an explicit qualification fixture and must not be inferred from owner-level unit coverage.

## 7. Integration, rollback and capability ceiling

Production composition uses the existing SQLite owner through `hepta-memory`, the owner/generation-fenced Agentd control socket, the existing durable native dispatch journal, and the existing native App Server worker. Cognitive text remains `AdditionalContextKind::Untrusted`; digests are provenance and final compare inputs, not authority tokens. Rollback invalidates incompatible cache/snapshot generations; cached reads cannot suppress immediate revocation that the owner observes before finalization.

The synchronous `AuthoritativeCognitiveSnapshotProvider`/`read_authoritative` surface is retained for source compatibility but explicitly deprecated for production use. It is qualification/compatibility machinery around the host-vector envelope, not a second production route. Production acquisition/freshness semantics live in the durable Lane C cut plus explicit revalidation/finalization path.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective when observed at owner finalization or later host authority checks. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `read_v2` in [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs); `DurableCognitiveSnapshot` in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs); owner `read` and `finalize` in [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs); `AgentdClient::finalize_cognitive_context` in [codex-rs/hepta-agentd/src/client.rs](../../../codex-rs/hepta-agentd/src/client.rs); `DurableInferenceControl::stop_native_before_turn_start` in [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs); pre-`TurnStart` finalization in [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs).
- **State and recovery:** `read_v2` reuses V1 selection, adds request-bound canonical bytes, sorts citations and accounts for byte-limit omissions. `DurableCognitiveSnapshot` reads an owner-acquired SQLite cut; native V2 bytes are not an admitted ModulePort/wire protocol. Agentd finalization reacquires the owner cut and reproduces both snapshot and read digests; conflict/unavailability fails closed. Native durable control can release a synced dispatch intent only while the trusted host can prove no `TurnStart` has been sent.
- **Product composition:** Agentd publishes the bounded context only after its first cut revalidation. The native infer worker retains the receipt, creates/verifies the exact App Server thread, rechecks Agent generation, syncs dispatch intent, calls `CognitiveContextFinalize`, then sends `TurnStart`. Context remains untrusted at the App Server boundary.
- **Authority abstraction status:** `AuthoritativeSnapshotV1` remains public for optional generation-vector qualification binding. `AuthoritativeCognitiveSnapshotProvider`, `SnapshotAcquisitionRequestV1`, `AuthoritativeReadResultV1`, and `read_authoritative` remain source-compatible exports but are deprecated as production entrypoints; no second synchronous provider semantics layer is composed into the product path.
- **Source tests:** [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs](../../../codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), the strict Agentd protocol round-trip test in [codex-rs/hepta-agent-protocol/src/lib.rs](../../../codex-rs/hepta-agent-protocol/src/lib.rs), and the durable pre-turn-stop regression in [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs). `finalization_rejects_context_tombstoned_after_agentd_read` deterministically covers the post-response owner mutation window. These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), and [docs/modules/cognitive.read/IMPLEMENTATION_MAP.json](../../../docs/modules/cognitive.read/IMPLEMENTATION_MAP.json).
- **Machine status:** `implemented=true`, `composed=true`, `qualified=false`. The implementation map binds the owner root, native operations and named product callers to exact Git tree/blob objects so relevant source drift fails verification rather than silently preserving a stale composed claim.
- **Remaining work:** run exact-head and deterministic synthetic-merge qualification for the new finalize path; add/execute the full transport-level READ-08 race fixture proving no `TurnStart` after post-response mutation; obtain independent semantic/target-host acceptance. The historical cut and a successful finalization remain observations, not leases over writes occurring after finalization returns.
