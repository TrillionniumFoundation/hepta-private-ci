# cognitive.read: implementation design

Parent: `docs/modules/cognitive.read/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded V2 read projection and existing SQLite-cut consumer implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Lower-level primitive:** `read_v2` in [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs) remains the bounded typed snapshot projection primitive. It validates selector/profile consistency, stable ordering/deduplication, result/byte ceilings, source-cut binding and stale/missing diagnostics, but it does not by itself prove that caller-supplied snapshot bytes still belong to a current retained authoritative generation.
- **Authoritative product contract:** `read_authoritative` in [codex-rs/hepta-cognitive-read/src/authoritative.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative.rs) binds scope, purpose, authority epoch, minimum memory/tombstone frontiers, generation-vector digest, lease/deadline, snapshot receipt and the bounded `read_v2` receipt. Product callers requiring current-authority semantics use this entrypoint rather than calling `read_v2` directly.
- **Production owner adapter:** [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs) provides `LaneCAuthoritativeSnapshotProvider` over one owner-acquired immutable SQLite cut. The provider has no store/write handle. `revalidate_lane_c_authoritative_snapshot` validates the envelope and then reacquires the canonical owner cut, requiring exact memory/source/tombstone/fact frontiers, knowledge-graph generation and snapshot digest before consumption.
- **Named product caller:** [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs) now composes `lane_c_snapshot -> LaneCAuthoritativeSnapshotProvider -> read_authoritative -> revalidate_lane_c_authoritative_snapshot`. [codex-rs/hepta-agentd/src/state_control.rs](../../../codex-rs/hepta-agentd/src/state_control.rs) supplies the current runtime generation as the host authority epoch and rejects the response if that generation changes across the asynchronous read.
- **Explicit owner-local subset:** the Agentd cognitive-context read consumes the cognitive owner cut and optional separately revalidated ranker. Model/tokenizer/template/tool-schema dimensions are outside this read boundary and are represented by one domain-separated unbound sentinel under purpose `agentd-cognitive-context-owner-local-v1`; they are not claims that downstream model generations were validated by `cognitive.read`. A later model-attachment boundary must bind its own concrete model/prompt/tool generations.
- **Source tests:** [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs), [codex-rs/hepta-cognitive-read/src/authoritative_tests.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs), [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs), and [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs). The Lane-C suite includes an adversarial authoritative-provider test that advances an owner frontier after read and separately expires the lease; both final revalidations fail closed.
- **Completed delivery fence:** exact Lane-C revision/content/frontier revalidation before delivery is implemented and is no longer a remaining-work item.
- **Remaining qualification work:** run exact-candidate compilation/tests/Clippy and product qualification, and retain the outer Agentd lifecycle-generation fence through final response delivery. Any future backend must acquire an immutable owner-defined cut and implement the authoritative provider boundary; independently querying moving `visible` and `fetch` state is not an admissible snapshot implementation.

