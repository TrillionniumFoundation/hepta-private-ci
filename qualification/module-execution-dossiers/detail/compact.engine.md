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

- **Canonical engine entrypoints:** `build_qualified_candidate` and `prove_compaction` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs). The former legacy `compact` checkpoint type/path is removed so deletion, lineage, protected-reference and resource-budget invariants cannot be bypassed.
- **Context-compaction contract:** the qualified path enforces retained record/byte/token ceilings, semantic payload byte/token ceilings, exact source-snapshot binding and exact tokenizer binding. Semantic content is supplied only as an immutable generator artifact/receipt; the pure engine does not invoke a model. The checkpoint payload digest therefore represents the bound semantic context artifact rather than a second ad-hoc checkpoint type.
- **Independent proof:** `CompactionProofV2` binds candidate/checkpoint identity, evaluator identity and implementation, evaluation artifact, attestation, signature digest, signature-verification receipt, retained-query suite, reconstruction obligation, contradiction holdout and deletion cutoff. The proof remains authority-free and does not self-authenticate the external evaluator.
- **State, publication and recovery:** `codex-rs/hepta-memory/src/qualified_compact_store.rs` persists the canonical checkpoint/proof in the existing cognitive SQLite owner using migration `0011_qualified_compact_checkpoints.sql`. Publication revalidates a live bound lease inside `BEGIN IMMEDIATE`, performs generation/predecessor CAS and writes one immutable row. Reopen reconstructs the full contracts, recomputes digests and checks durable predecessor continuity; corrupt rows fail store open.
- **Product caller:** `AgentdProductionWriterHost::publish_compaction_checkpoint` in `codex-rs/hepta-agentd/src/production_writer_host.rs` is the named caller. It is available only through the externally verified `ProductionDurableWriter`; default Agentd startup does not mint a writer capability.
- **Source tests:** [codex-rs/hepta-compact-engine/src/qualified_tests.rs](../../../codex-rs/hepta-compact-engine/src/qualified_tests.rs), `codex-rs/hepta-memory/src/qualified_compact_store_tests.rs`, `codex-rs/hepta-agentd/src/production_writer_host_tests.rs`, and `codex-rs/hepta-cognitive-types/src/lane_c_tests.rs`. The engine suite includes a 4,096-record deterministic/budget regression; the Agentd suite drives the authorized product caller through durable SQLite publication and restart/reopen. CI additionally emits exact-head test identities for source and deterministic synthetic-merge candidates.
- **Implementation and operating references:** [docs/modules/compact.engine/TECHNICAL.md](../../../docs/modules/compact.engine/TECHNICAL.md), [docs/learning/NEURAL_BIOMIMICRY_SPEC.md](../../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md).
- **Remaining target work:** replay scheduling and skill induction remain separate target capabilities. Independent semantic acceptance, target-host qualification, activation, promotion and release remain external gates and are not implied by source implementation.
