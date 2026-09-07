# compact.engine: implementation design

Parent: `docs/modules/compact.engine/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-compact-engine`.
Packages: `MEM-5-COMPACT`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
