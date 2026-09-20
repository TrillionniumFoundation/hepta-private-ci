# compact.engine: implementation design

Parent: `docs/modules/compact.engine/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: canonical V3 planning/candidate construction, signed independent qualification, and a durable CognitiveStore publication/reload owner are source-composed. Agentd contains the named internal product caller. Exact-head/merge-candidate execution, concrete semantic-compactor/evaluator deployment identities, independent acceptance and promotion remain separate evidence gates.

## 1. Source and work envelope

Owner-native root: `codex-rs/hepta-compact-engine`.
Durable owner integration: `codex-rs/hepta-memory/src/production_compact.rs`.
Named product caller: `codex-rs/hepta-agentd/src/compact_checkpoint_host.rs`.
Package: `MEM-5-COMPACT`.

The compact engine owns compaction semantics, not the cognitive database or Agentd lifecycle. The durable writer remains in the existing `cognitive_1.sqlite3` owner; the caller remains Agentd. No second authority/store/execution spine is introduced.

## 2. Public operations and canonical contracts

Owner-native operations are:

- `plan_compaction(snapshot, generation, predecessor, policy, inputs) -> CompactionPlanV3`.
- `build_qualified_candidate(plan, semantic_receipt) -> QualifiedCompactionCandidateV3`.
- `prove_compaction(candidate, trusted_evaluator, signed_qualification) -> CompactionProofV2`.

The only canonical checkpoint contract exposed by compact.engine is `CompactCheckpointV1` from `hepta-cognitive-types`. The previous record-only `compact()` and crate-local `CompactCheckpoint` path are removed rather than deprecated because they could bypass deletion/non-resurrection qualification.

`CompactionPolicyV3` binds algorithm, compatibility, tokenizer, semantic-compactor identity/implementation, record cap, byte cap, token cap and protected references. Each input binds encoded bytes, token count, retention reason and tokenization receipt. A semantic compactor does not receive publication authority: it returns `SemanticCompactionReceiptV1`, binding exact source manifest, tokenizer, implementation, output digest/bytes/tokens.

## 3. Deletion, loss and deterministic selection

All revisions are normalized per record id. Revision chains must begin at revision 1, be contiguous and bind exact predecessor digests. Once a tombstone is observed, a later live revision is rejected. Tombstoned heads cannot be retained.

Protected ids must exist in the source cut. Protected live heads are selected first and must fit every record/byte/token budget. Optional live heads are ordered deterministically by retention priority and identity and are admitted only while every budget remains satisfied. `CompactionLossReportV3` accounts for live/deleted/retained/omitted records and byte/token partitions.

The support manifest hashes the semantic input identities, including record digest, priority, retention reason, encoded bytes, token count and tokenization receipt. Candidate construction rejects semantic receipts whose source manifest, tokenizer or compactor implementation differs from the plan.

## 4. Independent qualification and proof provenance

`CompactionQualificationV3` binds evaluator identity, evaluator implementation digest, evaluator attestation digest, evaluation artifact digest, retained-query suite, reconstruction obligation, contradiction holdout and deletion non-resurrection outcome.

A `TrustedCompactionEvaluatorV1` is supplied by the host trust boundary. `prove_compaction` verifies an Ed25519 signature over the exact candidate digest and qualification fields. `CompactionProofV2` then binds the V1 semantic proof plus candidate digest, evaluator identity, implementation, attestation, evaluation artifact, evaluator-key digest and signed-qualification digest. Self-asserted pass booleans without a trusted signature cannot construct a proof.

## 5. Durable owner transaction and recovery

The production writer is `CognitiveStore::publish_production_compact_checkpoint` in the existing Agent-local `cognitive_1.sqlite3`. It reuses the append-only `cognitive_compact_events` table but uses an independent production namespace and encoding; local-development lease-bound encodings are rejected if mixed into the production journal.

Publication opens `BEGIN IMMEDIATE`, reloads/verifies the production event chain, enforces stable operation-id replay, exact predecessor digest and successor generation CAS, validates the source authority epoch/generation fence, inserts one complete publication event, then commits. A crash/fault before commit leaves the predecessor selected.

Reload verifies row/event identity, owner/authority epochs, fencing token, sequence, previous/event digests, operation-id uniqueness and contiguous checkpoint lineage. It reconstructs the complete `CognitiveSnapshotKeyV1`, `CompactCheckpointV1` and `CompactionProofV2` and calls their validators before returning the current checkpoint. Corrupt or forged rows fail closed.

## 6. Named product caller

Agentd composes `AgentdCompactCheckpointHost` whenever its CognitiveStore is available. The caller requires a Running/Ready/unfenced Agentd lifecycle, derives owner epoch from the refreshed fleet lifecycle generation and derives the fence from operation id + exact checkpoint digest + owner epoch. Callers cannot supply their own owner epoch or arbitrary raw fence.

Publication is durable before Agentd's post-publication generation recheck. If lifecycle fencing changes concurrently, Agentd fails closed; stable operation-id replay/current-checkpoint query provides deterministic reconciliation without a second publication.

## 7. Verification cases

- COMPACT-01: protected live references survive deterministic selection and record/byte/token budgets.
- COMPACT-02: `Live -> Tombstone -> Live` is rejected and tombstoned heads never reach a checkpoint.
- COMPACT-03: reordered source inputs produce the same plan/candidate digests.
- COMPACT-04: semantic receipt source/tokenizer/implementation mismatch is rejected.
- COMPACT-05: unsigned/tampered evaluator qualification cannot produce `CompactionProofV2`.
- COMPACT-06: publish -> process reopen -> reload reconstructs the exact checkpoint/proof.
- COMPACT-07: crash before commit leaves the predecessor current.
- COMPACT-08: concurrent successors have one CAS winner.
- COMPACT-09: forged SQLite event data fails reload verification.
- COMPACT-10: a 4096-head bounded plan remains deterministic and within byte/token accounting.

These source test identities are not exact-head or target-host pass receipts.

## 8. Current native implementation

- **Implemented entrypoints:** `plan_compaction` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs); `build_qualified_candidate` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs); `prove_compaction` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs).
- **Durable owner:** [codex-rs/hepta-memory/src/production_compact.rs](../../../codex-rs/hepta-memory/src/production_compact.rs), using the existing CognitiveStore database and append-only compact event table.
- **Named caller:** [codex-rs/hepta-agentd/src/compact_checkpoint_host.rs](../../../codex-rs/hepta-agentd/src/compact_checkpoint_host.rs), composed by Agentd runtime startup.
- **Source tests:** [codex-rs/hepta-compact-engine/src/qualified_tests.rs](../../../codex-rs/hepta-compact-engine/src/qualified_tests.rs), [codex-rs/hepta-memory/src/production_compact_tests.rs](../../../codex-rs/hepta-memory/src/production_compact_tests.rs), [codex-rs/hepta-agentd/src/runtime_tests.rs](../../../codex-rs/hepta-agentd/src/runtime_tests.rs).
- **Capability ceiling:** compact.engine does not itself run a model/LLM semantic compressor, mint evaluator trust, mutate source facts, dispatch network effects or grant release/promotion authority.
- **Remaining repository/evidence work:** run and retain exact-head plus deterministic merge-candidate receipts for this candidate; bind concrete production semantic-compactor and evaluator trust/attestation identities before claiming end-to-end semantic-compaction activation. Replay scheduling and skill induction remain separate target capabilities and are not implied by checkpoint closure.
