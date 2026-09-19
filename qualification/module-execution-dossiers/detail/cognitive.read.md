# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: authoritative crate-native read is product-composed through the canonical SQLite owner and agentd; independent CI/target-host acceptance and release gates remain distinct and are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-read`.
Packages: `MEM-READ-1-SNAPSHOT-PORT`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`acquire_snapshot(scope, source_frontiers, generations) -> SnapshotReadPort`; `read_ids(snapshot, ids, fields) -> BoundedReadResult`; `revalidate(packet, current_revocation_frontier) -> ValidatedAttachment | Stale`. No mutation/SQL-writer handle is exposed. Cross-owner reads bind a coherent declared cut and report missing/lagging owners explicitly.

## 3. State records and transaction design

No authoritative domain facts. Cache keys include principal/purpose, source/event revisions, tombstone frontier, KG/engram generation, encoder/preprocessor identity and requested fields. Cache values are bounded redacted projections. A read snapshot holds leases/pins on actual source generations and releases them on completion/cancellation.

## 4. Deterministic algorithm and scheduling

Authenticate purpose and scope before lookup; acquire the declared coherent source cut; fetch exact revisions; apply redaction and current revocation; return bounded facts with provenance. Before physical model-request attachment, revalidate the packet against one current compatible snapshot. Do not combine source rows from different frontiers because each individual read succeeded.

## 5. Capacity and performance profile

Pilot read <= 512 IDs and <= 1 MiB encoded result subject to context limits; snapshot lifetime <= the request deadline; cache bytes and pins are host-profile ceilings. A slow reader must expire or receive unavailable rather than hold unbounded history.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- READ-01: a packet becomes stale when one selected source revision or tombstone frontier changes.
- READ-02: cross-principal cache lookup is rejected even for equal query text.
- READ-03: cancellation releases read pins/descriptors without granting write access.
- READ-04: incomplete projection generation is reported unavailable, never presented as a complete snapshot.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Implement the source-store reader adapter and fixture port against identical contracts. The no-owned-state test is required. Rollback invalidates incompatible cache/snapshot generations; cached reads cannot suppress immediate revocation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Production entrypoint:** `read_authoritative` in [codex-rs/hepta-cognitive-read/src/authoritative.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative.rs). `read_v2` in [v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs) is now a crate-internal bounded projection primitive rather than a product-facing correctness boundary.
- **Authoritative contract:** `CognitiveReadGenerationVectorV1` binds scope, purpose, memory/source/tombstone/knowledge-fact frontiers, graph generation, host generation and authority epoch. `AuthoritativeSnapshotV1` additionally binds provider identity, immutable snapshot, bounded lease and receipt digest. `AuthoritativeReadResultV1::revalidate_for_current_snapshot` fails closed when the provider, generation vector, snapshot, request binding or original lease changes.
- **Canonical production provider:** [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs) implements `LaneCAuthoritativeSnapshotProvider`. The SQLite owner fills every cognitive frontier itself; the host supplies only purpose, host generation and authority epoch. This avoids manufacturing unrelated prompt/model/compact generations.
- **Product composition:** [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs) acquires the authoritative provider, executes `read_authoritative`, binds the context plan to the authoritative read digest, and revalidates the exact owner cut/vector/original lease immediately before consumption. [state_control.rs](../../../codex-rs/hepta-agentd/src/state_control.rs) refreshes lifecycle state and requires the authority epoch observed at read start to remain current before publication.
- **Revision fence status:** exact Lane-C snapshot/revision/content revalidation before delivery is implemented and must not be listed as pending work.
- **Source tests:** [authoritative_tests.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs), [v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), and [cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs). The agentd adversarial test mutates the real SQLite owner after read construction but before final consumption and requires fail-closed conflict.
- **Remaining gates:** CI and target-host execution receipts for this revision, independent semantic review, operator acceptance, canary/promotion and release remain external evidence gates. Cross-module wire registration is only required if this crate-native boundary is later exposed as a wire protocol.
