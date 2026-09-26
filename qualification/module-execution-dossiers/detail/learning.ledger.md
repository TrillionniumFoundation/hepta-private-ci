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

`LedgerWriter::append_unlearning(expected_anchor, UnlearningLineageRequestV1, exact_dataset_receipt, signed_authority)`;

`LedgerWriter::freeze_dataset(DatasetFreezePlanV2, signed_evaluator)`;

`LedgerWriter::revalidate_dataset_snapshot(receipt, now)`;

`LedgerWriter::rotate_segment(next_segment, expected_anchor, authorized_segment_directory)`;

`append_observed_outcome_v2` / `append_outcome_credit_v2` in
`codex-rs/hepta-intelligence` are the source-composed terminal caller surface.

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

`UnlearningLineageEventV1` durably binds the canonical source event digest, exact
frozen dataset identity/digest, a cross-owner artifact handoff identity, authority
and reason. Before append, `LedgerWriter` verifies the self-describing dataset
receipt and proves that its canonical source digest set actually contains the
named source record. Replay rechecks the persisted source-event digest against
canonical history. Publication logically revokes the source record, so the active
projection excludes it and dependent outcome/credit facts. `artifact_id` is not
an artifact-registry membership proof: `learning.artifacts` remains authoritative
for dataset→artifact membership, withdrawal fanout and descendant revocation.
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
retained independently from the suspect ledger. Writer construction requires
host-authorized handles for the actual ledger/segment and witness containing
directories and synchronizes them before acknowledgement. Segmented rotation is
invoked through `LedgerWriter::rotate_segment`; the successor file is synced,
the supplied containing directory is synced, and only then is the new segment
topology witnessed.

## 5. Trust-root and signer distribution

`LearningEvidenceVerifierV1` provides Ed25519 admission and validates
scope/objective/epoch, validity windows, signer role, revocation, principal,
credential chain, key and controller separation.

Product writer construction requires `ActivatedLearningTrustV1`, created by
`activate_learning_trust(&LearningTrustRootV1, SignedLearningTrustDistributionV1, previous, now)`.
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
- pending and censored outcome counts, including decisions for which no Outcome row exists yet.

The caller cannot self-report those cuts. `DatasetSnapshotReceiptV3` remains
self-verifying and deny-all. `LedgerWriter::revalidate_dataset_snapshot` is the
final-use currentness check: it verifies the historical receipt and requires
every frozen source event digest to remain present in the current canonical
active projection. A later correction, revocation or unlearning event therefore
invalidates stale use without rewriting history.

Logical unlearning is distinct from physical erasure and parameter unlearning.
`learning.ledger` proves the source→dataset edge and preserves the artifact handoff
identity; `learning.artifacts` proves the dataset→artifact/descendant relation and
owns withdrawal/revocation publication. Neither owner may infer the other's fact.
Deployment owners still owe the live cross-owner handoff, derived-artifact rebuild,
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
retained-history memory. `examples/target_host_qualification.rs` is the
executable measurement harness for a named target host. It records exact
commit/tree/binary identity, append and rotation p50/p95/p99, sustained append
throughput, reopen time, storage bytes and RSS, while explicitly leaving
power-loss, longitudinal-efficacy and activation qualification false.

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
- LEDGER-07: unlearning requires exact dataset membership, persists the verified
  source/dataset digests, survives replay and prevents causal non-resurrection.
- LEDGER-08: canonical protocol adapters reject unknown fields and round-trip
  registered views.
- LEDGER-09: index checkpoint tampering is detected and canonical replay remains
  authoritative.
- LEDGER-10: segmented rotation/recovery preserves the external witness frontier.
- LEDGER-11: final-use dataset revalidation rejects a frozen source set after
  correction, revocation or unlearning removes any source from the current active
  projection.
- LEDGER-12: lost acknowledgement, corrupt/missing witness history, containing-
  directory durability and actual process death between ledger sync and witness
  advancement fail closed or reconcile the exact original identity.
- LEDGER-13: the source-composed intelligence terminal closure records
  authenticated Outcome/correction plus one conserved CreditBatch through
  `LedgerWriter`, and preserves an already-committed Outcome when the later
  credit append needs reconciliation.

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
- **Trust distribution:** pinned `LearningTrustRootV1`, root-signed
  `SignedLearningTrustDistributionV1`, `ActivatedLearningTrustV1`, and
  `activate_learning_trust` in
  [src/trust_distribution.rs](../../../codex-rs/hepta-learning-ledger/src/trust_distribution.rs).
- **Cryptographic evidence admission:** `LearningEvidenceVerifierV1` in
  [src/signed_evidence.rs](../../../codex-rs/hepta-learning-ledger/src/signed_evidence.rs).
- **Canonical protocol views:** [src/protocol.rs](../../../codex-rs/hepta-learning-ledger/src/protocol.rs).
- **Verifiable read index:** [src/checkpoint.rs](../../../codex-rs/hepta-learning-ledger/src/checkpoint.rs).
- **Source-composed Decision consumer:**
  `run_evaluated_shadow_v1` in `codex-rs/hepta-intelligence` accepts
  `LedgerWriter` and generator-signed `ProductionDecisionV2`; it no longer
  appends a V1 `Decision` through `DurableLearningJournal`.
- **Source-composed terminal consumer:**
  `append_observed_outcome_v2` and `append_outcome_credit_v2` in
  `codex-rs/hepta-intelligence/src/outcome_credit_v2.rs` require the current
  active Decision run/episode binding and use `LedgerWriter` for authenticated
  Outcome/correction and conserved CreditBatch. A Credit failure after Outcome
  commit preserves the Outcome receipt for exact reconciliation.
- **Target-host harness:** `codex-rs/hepta-learning-ledger/examples/target_host_qualification.rs`.

## 11. Source closure versus external gates

Repository-controlled source convergence now covers the requested writer,
atomic-credit, correction-lineage, ledger-derived freeze, unlearning lineage,
trust distribution, independent witness, canonical protocol adapters and
verifiable index source surfaces. Current exact-head and synthetic-merge CI
still determine whether this particular candidate is source-qualified.

The repository cannot self-issue the remaining external/product evidence:

- daemon-owned invocation of the source-composed Decision/terminal callsites;
- actual deployment directory ownership/capability identity and physical durability;
- production root-public-key provisioning/rotation ceremony and trust-distribution transport/key custody;
- live independent outcomes;
- target-host latency/storage/recovery/throughput/RSS receipts produced on each selected deployment class;
- physical deletion/backups or model-unlearning proof;
- independent semantic acceptance, canary, selection, promotion or release.

The source-composed intelligence callers are still library/product-path source
composition, not a daemon-owned live deployment. They do not change
`productionImplementation=false` or `productExecutionProved=false` until the
runtime owner binds them to real terminal observations and current production
trust/storage dependencies and exact product execution is evidenced.

## 12. Exact signed-append acknowledgement recovery

`LedgerWriter::authenticated_append_identity` produces a bounded, non-authorizing
identity for the existing caller intent: ledger binding, record ID, original
predecessor and complete signed-evidence digest. `LearningAppendIdentityV1`
encodes/decodes it with a versioned, bounded, closed-field format. The caller must
persist it before submission in its existing durable intent; this API creates no
second database, writer, authority or execution path.

`LedgerWriter::recover_authenticated_append` reads the validated owner index and
returns the original authenticated Decision/Outcome receipt. It never inserts a
missing event, runs a model, renews evidence or reauthorizes an external effect.
A one-event-late independent witness can advance only for the exact committed
record. An absent record is not evidence that an external effect did not happen.
Any subsequent new append still requires normal current signed admission.

The historical receipt remains readable after signature expiry or data withdrawal;
it does not restore dataset eligibility or roll back withdrawal. Tests cover a
real child-process exit without returning a receipt, independently lost witness
acknowledgement, payload-identity/predecessor/store substitution, bounded decoding,
and authenticated Outcome withdrawal followed by reopen. The child helper is
included in the seven targeted test cases; it is not a separate production role.

This owner recovery primitive does not close the daemon canonical handoff or
persist a not-yet-committed full request. Normal Agentd lifecycle installation,
physical App Server execution, real Laya training/serving, independent efficacy,
and current exact-head/base-merge qualification remain separate unfinished work.
No capability or production flag changes with this source addition.
