# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: authoritative SQLite snapshot provider and Agentd product caller are source-composed; exact-candidate qualification and independent acceptance remain external gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** `read_v2` in [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs) is the lower-level bounded projection primitive; `read_authoritative` and `AuthoritativeReadResultV1::validate_for_use` in [codex-rs/hepta-cognitive-read/src/authoritative.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative.rs) bind acquisition request, generation vector, lease, snapshot receipt and read receipt; `CognitiveStore::authoritative_lane_c_snapshot_provider` and `LaneCAuthoritativeSnapshotProvider` in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs) are the canonical SQLite production provider; the named product caller is [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs).
- **Product composition:** Agentd captures the current fleet lifecycle generation as the read authority epoch, acquires the owner cut through the authoritative provider, calls `read_authoritative`, binds the authoritative read digest into context planning, revalidates the optional ranker, then calls `revalidate_authoritative_lane_c_snapshot`. `state_control` refreshes lifecycle state after the read and refuses publication if the lifecycle generation changed.
- **State and recovery:** the SQLite owner supplies memory/source/tombstone/knowledge-fact/knowledge-graph frontiers from one transaction; the caller cannot forge those owner dimensions. Final-use validation rechecks request/receipt/vector digests, lease/deadline, exact owner cut and a fresh host vector. The Agentd path currently does not consume compact-checkpoint or prompt-registry records; those vector slots are explicit fixed not-consumed sentinels and must be replaced by real owner receipts if those dependencies become inputs.
- **Snapshot-isolation boundary:** the core reads a concrete immutable `CognitiveSnapshot`; the production adapter owns an immutable `DurableCognitiveSnapshot` inside an opaque authoritative provider. No moving `CognitiveSnapshotView` or split `visible()/fetch()` backend abstraction is present in the production path. A future backend must implement the authoritative immutable-provider semantics rather than independently querying moving state.
- **Source tests:** [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [codex-rs/hepta-cognitive-read/src/authoritative_tests.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs), [codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs](../../../codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), and [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs). The new adversarial cases cover authority/profile drift, lease expiry, owner-frontier advance, and a tombstone committed after context assembly but before final use. These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md) and [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work:** repository-controlled production composition is implemented in source. Exact-candidate CI must prove the branch and synthetic merge, and independent semantic review / target-host qualification / operator acceptance / promotion / release remain external gates. Any future cross-module wire format must still be registered through its existing owner.
