# learning.ledger: implementation design

Parent: `docs/modules/learning.ledger/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: additive native source implementation candidate; current exact-head and
synthetic-merge CI determine source qualification, while live product host
composition and independent acceptance remain separate. Common requirements:
`../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and
package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-ledger`.
Packages: `LRN-0-CAUSAL-LEARNING-CONTRACTS`,
`LRN-1-DURABLE-EPISODE-LEDGER`.

Concrete source mappings are recorded in
`../../../codex-rs/hepta-learning-ledger/NATIVE_MAPPING.md` and
`../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve one data
owner and one execution spine; do not create a parallel ledger.

## 2. Public operations and contract details

The product-facing source operation set is:

`LedgerWriter::append_decision(expected_anchor, ProductionDecisionV2, signed_generator)`;

`LedgerWriter::append_outcome(expected_anchor, AuthenticatedOutcomeV1, signed_observer)`;

`LedgerWriter::append_credit_batch(expected_anchor, CreditAllocationBatchV1, signed_allocator)`;

`LedgerWriter::append_unlearning(expected_anchor, UnlearningLineageRequestV1, signed_authority)`;

`LedgerWriter::freeze_dataset(DatasetFreezePlanV2, signed_evaluator)`;

`LedgerWriter::rotate_segment(next_segment, expected_anchor)`.

The stable V1 event tags and durable encoding remain readable. Raw
`LearningLedger`, `DurableLedger`, `SegmentedLedger` and
`DurableLearningJournal` are compatibility/testing backends. New composed
callers use `LedgerWriter`, which owns the backend handle, activated trust
distribution and independent witness.

The source additionally exposes pure compatibility validators
`verify_independent_roles`, `validate_authenticated_outcome`,
`validate_candidate_set_completeness`, `finalize_credit_batch` and
`freeze_dataset`. Those pure functions do not replace the production writer.

## 3. State records and transaction design

The module owns `learning_episode_ledger`, `learning_credit_ledger` and
`learning_unlearning_lineage`.

`AuthenticatedDecisionRecordV2` binds the run snapshot, objective, policy,
complete generator-relative candidate set, selected action, propensity,
generator controller/credential/signing key/scope/epoch and the exact admitted
evidence digest.

`AuthenticatedOutcomeRecordV2` binds independent observer
controller/credential/key/scope/epoch, reward units, observation time,
delay-profile/watermark state, correction predecessor and evidence digest.
Correction is a linear append-only graph: a root is unique per episode; every
correction predecessor must exist, belong to the same episode, remain active and
be the current head. Therefore stale branches, forks and cycles reject before
publication.

`CreditAllocationBatchRecordV2` is one durable publication unit. Targets are
canonicalized and deduplicated; the referenced outcome must be the current
terminal outcome with exactly the same terminal value; allocator identity and
controller must be independent from generator and observer; and allocations plus
residual must equal the terminal outcome exactly in Q32 units. A second committed
batch for the same terminal outcome rejects.

`UnlearningLineageEventV1` explicitly binds source record, dataset snapshot,
artifact, authority and reason. Publication logically revokes the source record;
the active projection excludes the source and dependent outcome/credit facts.
Audit bytes remain immutable.

## 4. Deterministic commit, acknowledgement and recovery

The production sequence is:

1. host supplies an activated immutable signer distribution;
2. verify signed evidence, role, scope, objective, epoch, validity and controller;
3. validate semantic invariants without mutation;
4. compare the exact predecessor;
5. encode one canonical append frame;
6. append and `sync_all` the ledger;
7. publish the deterministic core state;
8. append and `sync_all` the independent HEPTLW01 witness frontier;
9. acknowledge externally.

If step 8 is uncertain after step 6, return
`IndeterminateAfterLedgerCommit`. Reopen and reconcile the original identity;
do not create another record. A ledger may lead its witness by one record only
for that lost-acknowledgement case.

Anchored recovery never falls back to unanchored recovery. The witness is
retained independently from the suspect ledger. Segmented rotation is invoked
through `LedgerWriter::rotate_segment`; the new segment topology is witnessed
before success is reported.

## 5. Trust-root and signer distribution

`LearningEvidenceVerifierV1` provides Ed25519 admission and validates
scope/objective/epoch, validity windows, signer role, revocation, principal,
credential chain, key and controller separation.

Product writer construction requires `ActivatedLearningTrustV1`, created by
`activate_learning_trust(LearningTrustDistributionV1, previous, now)`.
Distribution generation must advance exactly one step; effective time is
monotonic; authority epoch cannot roll back; the activated state is
content-addressed. The host remains responsible for distribution transport,
current key custody, controller governance and revocation publication.

## 6. Dataset freeze and unlearning non-resurrection

`DatasetFreezePlanV2` deliberately contains only the snapshot identity,
objective and inclusion policy. `freeze_dataset_from_ledger` rebuilds current
canonical state and derives:

- exact ledger head and eligible frontier;
- active authenticated source-record digests;
- current outcome watermark;
- correction frontier digest;
- revocation/unlearning frontier digest;
- pending and censored outcome counts.

The caller cannot self-report those cuts. `DatasetSnapshotReceiptV3` remains
self-verifying and deny-all.

Logical unlearning is distinct from physical erasure and parameter unlearning.
Source→dataset→artifact lineage prevents use of revoked ancestry in the active
projection, but deployment owners still owe derived-artifact rebuilding,
physical deletion/backup handling and any model-level unlearning process.

## 7. Canonical protocol compatibility

`src/protocol.rs` provides explicit Rust compatibility views with the registered
names:

- `LearningDecisionV1`;
- `OutcomeReceiptV1`;
- `CreditAssignmentReceiptV1`;
- `DatasetSnapshotV1`;
- `LearningEpisodeV1` and its outcome watermark.

Encoding is bounded canonical JSON and rejects unknown fields. Views are derived
from stronger V2 durable records. A legacy JSON object is not accepted as
authenticated V2 evidence.

## 8. Capacity, checkpoint and read performance

The stable single-file profile and segmented limits remain bounded. Segmented
history preserves one global sequence/hash chain across rotation.

`LedgerIndexCheckpointV1` is a rebuildable content-addressed read accelerator.
It binds the exact ledger anchor, sorted record index, activity state, current
authenticated outcome heads and revocation/unlearning frontier. Verification
rebuilds the complete checkpoint from canonical history; mismatch discards it.

The checkpoint supplies bounded binary record lookup and auditability but does
not turn canonical recovery into O(1), implement compaction, or cap total
retained-history memory. Target-host latency, reopen time, storage growth and
sustained throughput remain measurement requirements.

## 9. Concrete verification cases

- LEDGER-01: ledger sync followed by acknowledgement/witness loss reconciles the
  exact original event.
- LEDGER-02: truncating acknowledged history fails anchored recovery.
- LEDGER-03: generator/observer/allocator identity or controller collisions
  reject.
- LEDGER-04: correction predecessor must exist, match the episode and equal the
  current head; stale branches/forks reject.
- LEDGER-05: one atomic credit batch must conserve the exact current terminal
  outcome.
- LEDGER-06: dataset freeze derives source rows and correction/revocation cuts
  from canonical ledger state.
- LEDGER-07: unlearning lineage survives replay and prevents causal
  non-resurrection.
- LEDGER-08: canonical protocol adapters reject unknown fields and round-trip
  registered views.
- LEDGER-09: index checkpoint tampering is detected and canonical replay remains
  authoritative.
- LEDGER-10: segmented rotation/recovery preserves the external witness frontier.

Passing source tests are not production deployment, live independent observation
or future-time efficacy.

## 10. Current native implementation

**Implemented entrypoints:** `LedgerWriter` in [codex-rs/hepta-learning-ledger/src/production.rs](../../../codex-rs/hepta-learning-ledger/src/production.rs); `LedgerWitnessStore` in [codex-rs/hepta-learning-ledger/src/witness.rs](../../../codex-rs/hepta-learning-ledger/src/witness.rs); `activate_learning_trust` in [codex-rs/hepta-learning-ledger/src/trust_distribution.rs](../../../codex-rs/hepta-learning-ledger/src/trust_distribution.rs); `build_ledger_index_checkpoint` in [codex-rs/hepta-learning-ledger/src/checkpoint.rs](../../../codex-rs/hepta-learning-ledger/src/checkpoint.rs).

- **Production-facing entrypoint:** `LedgerWriter` in
  [codex-rs/hepta-learning-ledger/src/production.rs](../../../codex-rs/hepta-learning-ledger/src/production.rs).
- **Durable backends:** `DurableLedger` and `SegmentedLedger` in
  [src/durable.rs](../../../codex-rs/hepta-learning-ledger/src/durable.rs) and
  [src/segments.rs](../../../codex-rs/hepta-learning-ledger/src/segments.rs).
- **Independent acknowledgement:** `LedgerWitnessStore` in
  [src/witness.rs](../../../codex-rs/hepta-learning-ledger/src/witness.rs).
- **Trust distribution:** `LearningTrustDistributionV1`,
  `ActivatedLearningTrustV1`, `activate_learning_trust` in
  [src/trust_distribution.rs](../../../codex-rs/hepta-learning-ledger/src/trust_distribution.rs).
- **Cryptographic evidence admission:** `LearningEvidenceVerifierV1` in
  [src/signed_evidence.rs](../../../codex-rs/hepta-learning-ledger/src/signed_evidence.rs).
- **Canonical protocol views:** [src/protocol.rs](../../../codex-rs/hepta-learning-ledger/src/protocol.rs).
- **Verifiable read index:** [src/checkpoint.rs](../../../codex-rs/hepta-learning-ledger/src/checkpoint.rs).
- **Source-composed qualification consumer:**
  `run_evaluated_shadow_v1` in `codex-rs/hepta-intelligence` now accepts
  `LedgerWriter` and generator-signed `ProductionDecisionV2`; it no longer
  appends a V1 `Decision` through `DurableLearningJournal`.

## 11. Source closure versus external gates

Repository-controlled source convergence now covers the requested writer,
atomic-credit, correction-lineage, ledger-derived freeze, unlearning lineage,
trust distribution, independent witness, canonical protocol adapters and
verifiable index source surfaces. Current exact-head and synthetic-merge CI
still determine whether this particular candidate is source-qualified.

The repository cannot self-issue the remaining external/product evidence:

- a named live product process/callsite using `LedgerWriter`;
- actual deployment directory ownership and physical durability;
- production trust-distribution transport/key custody;
- live independent outcomes;
- target-host latency/storage/recovery measurements;
- physical deletion/backups or model-unlearning proof;
- independent semantic acceptance, canary, selection, promotion or release.

The existing evaluated-shadow consumer is a source composition/qualification
consumer only. It does not change `productionImplementation=false` until a real
product caller and executable product tests are evidenced.
