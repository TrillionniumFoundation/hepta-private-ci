# cognitive.types: implementation design

Parent: `docs/modules/cognitive.types/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded record/snapshot types and Lane C generation contracts implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-cognitive-types`.
Packages: `MEM-0-TYPES`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`validate_memory_event(event, schema_profile) -> MemoryEventV1`; `validate_span(asset_manifest, modality, range) -> ModalitySpanRefV1`; `compile_snapshot_key(source_frontiers, generations, scope) -> SnapshotKey`. HNMF types cover event, modality span, engram, synapse, cue, recall packet, replay batch and forget reference. Modality-specific ranges are tagged unions, not untyped coordinate arrays.

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

- **Implemented entrypoints:** `build_snapshot` in [codex-rs/hepta-cognitive-types/src/lib.rs](../../../codex-rs/hepta-cognitive-types/src/lib.rs); `CognitiveSnapshotKeyV1` in [codex-rs/hepta-cognitive-types/src/lane_c.rs](../../../codex-rs/hepta-cognitive-types/src/lane_c.rs). Bounded record/snapshot types and Lane C generation contracts implemented.
- **State and recovery:** Stateless types canonicalize record ID/revision order and hash exact bounded records, citations and generation. These values contain no SQL connection or mutation authority; a snapshot digest does not authenticate its source.
- **Source tests:** [codex-rs/hepta-cognitive-types/src/lib_tests.rs](../../../codex-rs/hepta-cognitive-types/src/lib_tests.rs), [codex-rs/hepta-cognitive-types/src/lane_c_tests.rs](../../../codex-rs/hepta-cognitive-types/src/lane_c_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- **Remaining work:** Keep native snapshot/contract versions distinct from admitted cross-owner wire formats and bind every generation component to its actual owner.
