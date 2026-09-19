# compact.engine: implementation design

Parent: `docs/modules/compact.engine/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: canonical deletion-aware compaction qualification, context-budget binding, auditable proof V2, durable owner-store publication/reload and an explicit Agentd product caller are implemented in source. Exact-candidate execution, independent semantic acceptance, activation and release remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Primary root: `codex-rs/hepta-compact-engine`. Owner-store integration: `codex-rs/hepta-memory/src/production_compact.rs`. Product caller: `codex-rs/hepta-agentd/src/production_writer_host.rs`.
Package: `MEM-5-COMPACT`.

The compact engine owns deterministic candidate construction and proof binding, not an alternate state or authority spine. Durable publication reuses the cognitive owner store and the externally verified production-writer lease.

## 2. Public operations and contract details

The native product path is `build_qualified_candidate(...) -> QualifiedCompactionCandidateV2`, `prove_compaction(...) -> CompactionProofV2`, followed by the owner-store `ProductionDurableWriter::publish_compaction(...)`. Agentd exposes `qualify_and_publish_compaction(...)` as the explicit product consumer.

There is one checkpoint contract: `lane_c::CompactCheckpointV1`. The former weaker `compact()/CompactCheckpoint` surface is removed so tombstone, budget, provenance and proof requirements cannot be bypassed.

Target replay scheduling and skill induction remain separate capabilities; they are not implied by checkpoint construction.

## 3. State records and transaction design

`CompactCheckpointV1` binds checkpoint identity/generation, coherent Lane C source snapshot, support manifest, algorithm, retained payload digest, omitted-information digest, tombstone cutoff, predecessor and compatibility. `CompactionProofV2` additionally binds evaluator identity, exact evaluation artifact, evaluator implementation, attestation/signature digests, retained-query/reconstruction/contradiction holdouts and deletion cutoff.

Production publication stores a bounded canonical publication DTO in the existing append-only `cognitive_compact_events` owner table under a dedicated production journal identity. It creates no second database. Each row binds the production lease identity/head, authority and owner epochs, checkpoint generation, predecessor row digest and a lease/event binding digest.

## 4. Deterministic algorithm and scheduling

Inputs are grouped by stable record identity and every lineage must start at revision 1, advance contiguously and match predecessor digests. Once a tombstone occurs, a later live revision is rejected. Current live heads are ordered by protected status, retention priority, record ID and revision.

The retention policy binds algorithm, compatibility, tokenizer, maximum records, maximum serialized bytes, maximum tokens and protected references. The bound tokenizer must equal the source snapshot tokenizer. Protected live records must fit every budget. Optional records are selected deterministically in rank order while count, byte and token budgets permit; an oversized optional record may be omitted while a later smaller record still fits.

The support manifest binds each live record digest together with retention priority, retention-reason digest, serialized byte cost and token cost. Candidate validation recomputes payload/omission digests from the retained/omitted sets.

Semantic responsibility is explicit: the current engine is a deterministic selection/checkpoint compactor, not an unregistered generative summarizer. The caller supplies canonical serialized-byte and tokenizer-derived token observations for the exact materialization being compacted. A future semantic merge/summary algorithm must be a registered algorithm revision, retain provenance/citations/contradictions and pass the same independent reconstruction/holdout proof before publication.

## 5. Capacity and performance profile

Native hard ceilings are 65,536 input records, 4,096 protected references, 64 MiB retained serialized bytes and 16,777,216 retained tokens; a policy may set stricter limits. The tokenizer digest is snapshot-bound.

Focused regression coverage includes a 10,000-record deterministic batch. These are correctness/capacity fixtures, not host latency or throughput qualifications. Production SLOs still require exact-host measurement.

## 6. Concrete verification cases

- COMPACT-01: `Live -> Tombstone -> Live` is rejected on the only public candidate builder.
- COMPACT-02: protected live references precede optional records and must fit count/byte/token budgets.
- COMPACT-03: input order does not change the candidate; a 10,000-record batch produces the same retained/omitted result when reversed.
- COMPACT-04: proof V2 binds evaluator, evaluation artifact, evaluator implementation, attestation/signature and every semantic/deletion obligation.
- COMPACT-05: production publication is generation/predecessor-CAS protected; identical replay is idempotent and conflicting same-generation publication loses.
- COMPACT-06: reload verifies the complete durable row chain, lease/event binding and canonical checkpoint/proof digests; deliberate event corruption fails closed.
- COMPACT-07: a newly opened production writer reloads the committed checkpoint after process-state loss.

These are source test identities until an exact-head or deterministic merge receipt records execution.

## 7. Integration, rollback and capability ceiling

`AgentdProductionWriterHost::qualify_and_publish_compaction` is the registered product callsite. It constructs and proves the candidate before crossing the owner-store publication boundary. The production writer still requires an externally verified authority lease; this composition does not grant provider/external-effect, selection, activation, promotion or release authority.

Publication uses `BEGIN IMMEDIATE` and revalidates the live lease inside the same transaction. Generation plus predecessor digest is the checkpoint CAS. A failed construction or failed transaction leaves the prior committed generation current. Corrupt or discontinuous journal history fails closed on reload.

## 8. Current native implementation

- **Implemented entrypoints:** `build_qualified_candidate` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs); `prove_compaction` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs); `ProductionDurableWriter::publish_compaction` and `load_current_compaction` in [codex-rs/hepta-memory/src/production_compact.rs](../../../codex-rs/hepta-memory/src/production_compact.rs); `AgentdProductionWriterHost::qualify_and_publish_compaction` in [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs).
- **State and recovery:** canonical checkpoints/proof V2 are persisted through the existing WAL/FULL cognitive owner store. Publication is lease-bound and CAS-protected; reload revalidates the complete compact journal and canonical digests. No source fact is rewritten.
- **Source tests:** [codex-rs/hepta-compact-engine/src/qualified_tests.rs](../../../codex-rs/hepta-compact-engine/src/qualified_tests.rs), [codex-rs/hepta-memory/src/production_compact.rs](../../../codex-rs/hepta-memory/src/production_compact.rs). The latter contains the owner-store publication/restart/concurrency/corruption tests.
- **Implementation and operating references:** [docs/modules/compact.engine/TECHNICAL.md](../../../docs/modules/compact.engine/TECHNICAL.md), [docs/learning/NEURAL_BIOMIMICRY_SPEC.md](../../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md), [CALLERS.toml](../../../CALLERS.toml).
- **Remaining gates:** execute focused/package/all-target/strict-lint checks on the exact candidate and deterministic merge; retain independent semantic review/evaluator trust provisioning and target-host qualification; activation, operator acceptance, canary, promotion and release remain externally governed. Replay scheduling and skill induction remain separate target capabilities.
