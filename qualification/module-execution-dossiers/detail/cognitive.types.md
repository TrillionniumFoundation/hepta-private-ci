# cognitive.types: implementation design

Parent: `docs/modules/cognitive.types/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded record/snapshot types, Lane C generation contracts and canonical HNMF V1 Rust/JSON contracts implemented; exact-candidate execution, authenticated product composition and independent acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-types`.
Packages: `MEM-0-TYPES`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`MemoryEventV1::decode_json/validate`, `ModalitySpanRefV1::decode_json/validate` and `CanonicalJsonV1::encode_canonical_json/semantic_digest` are implemented in `codex-rs/hepta-cognitive-types/src/hnmf_v1`; `CognitiveSnapshotKeyV1` remains the typed Lane C generation key. Canonical HNMF types cover event, modality span, cross-modal binding, engram, synapse, cue, recall packet, outcome, replay selection, plasticity, cognitive-topology proposal and forget propagation. Modality-specific ranges are tagged unions, not untyped coordinate arrays.

## 3. State records and transaction design

No SQL, daemon or writer state. Memory event fields include event/episode ID, scope, observation interval, source digests, one or more spans, verification state, causal/temporal references, retention and correction/revocation links. An image region, audio sample interval, video frame range and text byte range use distinct units and bounds. Feature digests never replace original source/asset identity.

## 4. Deterministic algorithm and scheduling

Validate schema/discriminator; bound counts and ranges; reject impossible modality/coordinate combinations; canonicalize identifiers and profile fields; hash the semantically ordered representation. Preserve hypotheses and contradictory observations as distinct typed records. A self-model estimate is not a fact about a person or a permission statement.

## 5. Capacity and performance profile

Pilot <= 32 spans and <= 64 provenance/causal references per event, event metadata <= 256 KiB, source payload outside type receipts. Scalar/media range overflow rejects before asset access; no unbounded graph expansion in validation.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- CTYPE-01: text byte ranges cannot be passed as audio sample intervals.
- CTYPE-02: out-of-bounds frame/region/AST selectors and missing asset identity reject.
- CTYPE-03: correction and tombstone references remain distinct from normal evidence.
- CTYPE-04: canonical cross-language encoding preserves source and numeric-profile identities.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Register shared HNMF/native schemas through the contract owner before store/retrieval consumers. Source facts, rebuildable engrams and learned artifacts remain different types with different lifecycle rules. Version migration is explicit and never reinterpretation in place.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `build_snapshot` in [codex-rs/hepta-cognitive-types/src/lib.rs](../../../codex-rs/hepta-cognitive-types/src/lib.rs); `CognitiveSnapshotKeyV1` and Lane C shared structs in [codex-rs/hepta-cognitive-types/src/lane_c.rs](../../../codex-rs/hepta-cognitive-types/src/lane_c.rs); `CanonicalJsonV1` plus HNMF V1 contracts in `codex-rs/hepta-cognitive-types/src/hnmf_v1`.
- **Canonical wire:** explicit schema/version envelope, strict unknown-field rejection, per-schema encoded-size ceilings, deny-all authority, canonical collection ordering and exact decimal-text representation for 64-bit JSON identities/counters. The pre-existing global `TopologyProposalV1` remains owned by `learning.plasticity`; memory-structure proposals use `CognitiveTopologyProposalV1` to avoid changing an existing V1 protocol in place.
- **State and recovery:** Stateless types canonicalize bounded values and semantic digests. These values contain no SQL connection or mutation authority; integrity/digest success does not authenticate an external source or prove current revocation state.
- **Source tests:** [codex-rs/hepta-cognitive-types/src/lib_tests.rs](../../../codex-rs/hepta-cognitive-types/src/lib_tests.rs), [codex-rs/hepta-cognitive-types/src/lane_c_tests.rs](../../../codex-rs/hepta-cognitive-types/src/lane_c_tests.rs), and `codex-rs/hepta-cognitive-types/src/hnmf_v1/tests.rs`. CTYPE-01 through CTYPE-04 are implemented as native tests. These are test identities until exact-candidate execution receipts are current.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- **Remaining work:** exact-head focused/package/all-target/strict-Clippy/clean-worktree evidence, deterministic synthetic-merge evidence, authenticated product composition and independent acceptance. Production activation/release remain false.
