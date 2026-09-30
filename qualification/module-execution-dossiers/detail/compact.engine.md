# compact.engine: implementation design

Parent: `docs/modules/compact.engine/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded checkpoint and deletion-aware compaction qualification kernels implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-compact-engine`.
Packages: `MEM-5-COMPACT`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`plan_compaction(read_snapshot, retention_policy, resource_budget) -> CompactionCandidate`; `build_checkpoint(candidate) -> CompactCheckpoint`; `plan_replay(eligible_events, quotas, profile) -> ReplayBatch`; `propose_skill(episodes, precondition/effect schema) -> SkillCandidate`. No operation overwrites source facts or treats synthetic replay as real evidence.

## 3. State records and transaction design

`compact_checkpoint` binds source range/frontier, support manifest, algorithm/version, compressed payload digest, omitted-information description, tombstone cutoff, compatibility and predecessor. Procedural abstractions and semantic prototypes are proposals with source supports and confidence, not replacements for original events. Replay caches are rebuildable and inherit source deletion.

## 4. Deterministic algorithm and scheduling

Select eligible non-revoked events; apply per-source/task/modality quotas; rank by registered retention risk, prediction error, coverage and expected utility; build bounded summaries/checkpoints; verify retained-query and source-reconstruction obligations; publish through owner-approved state. Skills require explicit preconditions, termination, effect model and recovery. A missed consolidation window creates observable degradation, not unlimited catch-up work.

## 5. Capacity and performance profile

HNMF replay pilot <=4096 candidates and <=256 selected events; compaction batch and output byte ratio are profile-bound; source retention is not reduced by an unreviewed compression gain. Measure read utility loss, contradiction preservation, storage reduction, CPU and foreground interference.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- COMPACT-01: source facts and required provenance remain resolvable after checkpoint publication.
- COMPACT-02: a deleted event is excluded from replay and all derived checkpoint/skill candidates.
- COMPACT-03: old-task and contradiction holdouts detect information lost by compression.
- COMPACT-04: crash before publication retains the prior complete checkpoint; restore cannot select a revoked checkpoint.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Consolidation contributes future artifacts but cannot mutate the current neural snapshot. Prefer the simplest compressor/selector meeting retention and resource constraints. Rollback is a generation selection plus current-lineage revalidation, not restoration of deleted source material.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `compact` in [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs); `build_qualified_candidate` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs); `prove_compaction` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs). Bounded checkpoint and deletion-aware compaction qualification kernels implemented.
- **State and recovery:** Native checkpoints retain references and explicit omissions from a declared snapshot; the qualified path preserves protected live support, rejects missing protected inputs and validates retained/omitted/deleted/support/count/cutoff consistency. Terminal tombstone digests remain in the support manifest without entering replay payload. Selection-input metadata is committed, and `validate_against_inputs` rebuilds and compares the complete semantic candidate digest against an owner-retained frozen policy/input preimage, accepting equivalent citation permutations. Checkpoint IDs bind snapshot identity. Both paths reject live resurrection after an observed tombstone. Integrity is relative to the supplied complete revision chains; source membership, external completeness and current revocation require an authenticated consumer adapter. The crate neither rewrites source facts nor persists a selected checkpoint. Unpublished local V2 candidates use V3 support/candidate domains and require reconstruction of old candidates rather than an asserted wire-compatible migration.
- **Source tests:** [codex-rs/hepta-compact-engine/src/qualified_tests.rs](../../../codex-rs/hepta-compact-engine/src/qualified_tests.rs), [codex-rs/hepta-compact-engine/src/lib_tests.rs](../../../codex-rs/hepta-compact-engine/src/lib_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/modules/compact.engine/TECHNICAL.md](../../../docs/modules/compact.engine/TECHNICAL.md), [docs/learning/NEURAL_BIOMIMICRY_SPEC.md](../../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md).
- **Audit scope:** The [native API and adversarial audit](../../../docs/modules/compact.engine/TECHNICAL.md#18-native-api-and-adversarial-audit-scope), updated 2026-10-01 (Asia/Shanghai), documents algorithms, digest meanings, limits, rejection semantics and actual callsite inspection. Regression source and documentation do not establish passed exact-candidate execution.
- **Observation trust:** `prove_compaction` requires an exact candidate digest, then assembles caller-supplied suite digests and successful observation flags. It does not run holdouts/reconstruction or authenticate `evaluator_id`; independently authenticated, candidate-specific observations remain required before qualification/selection. The returned V1 proof is structural and carries no selection authority.
- **Actual composition:** No named product caller consumes the crate. hepta-memory's `cognitive_compact` checkpoint and lease-bound `local_compact_executor`/hooks are distinct local qualification types; Agentd's qualification writer uses those existing types without invoking this builder/proof assembler. Their persistence/recovery cannot be credited as native `compact_checkpoint` publication/reload.
- **Remaining work:** Bind authenticated coherent source reads, independent candidate-specific holdout/reconstruction evidence and owner publication/reload/revocation-aware selection; compose and execute a named caller through existing owner ports. Target replay scheduling and skill induction are separate capabilities, not implied by checkpoint construction. Current implementation/product/acceptance states remain governed by the implementation map and exact external receipts.
