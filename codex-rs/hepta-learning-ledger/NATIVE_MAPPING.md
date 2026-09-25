# `learning.ledger` native implementation mapping

This file maps the stable module guide and implementation dossier to concrete
Rust symbols. It distinguishes retained V1 compatibility surfaces from the
product-facing authenticated writer. Source composition is not target-host
qualification, independent acceptance, activation, promotion or release.

## Compatibility and state ownership

The existing V1 `LearningLedger`, `DurableLedger`, event tags 0..3 and
HEPTLR01 frame encoding remain readable. V1 APIs are retained for historical
replay, migrations and focused durability tests; there is no automatic V1-to-V2
reinterpretation.

New product composition uses `LedgerWriter`. It consumes the underlying durable
backend, a pinned-root-authenticated signer distribution and an independently durable witness,
so a caller using the owned writer cannot bypass V2 admission through the same
file handle.

Owned logical domains remain:

- causal decision and episode facts;
- independently observed outcome and correction facts;
- conserved credit facts;
- revocation and explicit unlearning lineage;
- immutable dataset-freeze receipts.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| legacy append/read compatibility | `LearningLedger::append` | `src/ledger.rs` | retained V1 |
| durable append and anchored reopen | `DurableLedger`, `LedgerAnchor`, `LedgerRecovery` | `src/durable.rs` | retained backend |
| segmented append/rotation/recovery | `SegmentedLedger` | `src/segments.rs` | implemented backend |
| unique product admission writer | `LedgerWriter` | `src/production.rs` | implemented/source-composed in evaluated shadow |
| authenticate pinned root + versioned signer distribution | `LearningTrustRootV1`, `SignedLearningTrustDistributionV1`, `activate_learning_trust` | `src/trust_distribution.rs` | implemented |
| recover an exact historical signed append | `LedgerWriter::authenticated_append_identity`, `LedgerWriter::recover_authenticated_append` | `src/production_recovery.rs` | Decision/Outcome/CreditBatch lookup; no new write authority |
| independently witness acknowledgements | `LedgerWitnessStore` | `src/witness.rs` | implemented |
| append authenticated decision | `LedgerWriter::append_decision` | `src/production.rs` | implemented |
| append authenticated/corrected outcome | `LedgerWriter::append_outcome` | `src/production.rs` | implemented |
| atomically append conserved credit | `LedgerWriter::append_credit_batch` | `src/production.rs` | implemented |
| append verified source→dataset unlearning lineage plus artifact-owner handoff identity | `LedgerWriter::append_unlearning` | `src/production.rs` | implemented |
| derive/freeze dataset from current ledger | `LedgerWriter::freeze_dataset`, `freeze_dataset_from_ledger` | `src/production.rs` | implemented |
| revalidate frozen dataset at final use | `LedgerWriter::revalidate_dataset_snapshot` | `src/production.rs` | implemented |
| sync containing directory before publication/topology witness | `sync_directory_handle`, `LedgerWriter::rotate_segment` | `src/production.rs` | implemented |
| source-composed terminal Outcome/correction/CreditBatch caller | `append_observed_outcome_v2`, `append_outcome_credit_v2` | `../hepta-intelligence/src/outcome_credit_v2.rs` | implemented; live daemon binding pending |
| canonical registered protocol views | `LearningDecisionV1`, `OutcomeReceiptV1`, `CreditAssignmentReceiptV1`, `DatasetSnapshotV1`, `LearningEpisodeV1` | `src/protocol.rs` | implemented |
| build/verify rebuildable read index | `build_ledger_index_checkpoint`, `verify_ledger_index_checkpoint` | `src/checkpoint.rs` | implemented |
| cryptographically admit signed evidence | `LearningEvidenceVerifierV1` | `src/signed_evidence.rs` | implemented |

## Production decision and identity boundary

`AuthenticatedDecisionRecordV2` durably binds the run-snapshot digest,
objective, policy, complete canonical candidate set, chosen candidate,
propensity, generator identity/controller/credential/signing key/scope/epoch and
the admitted evidence digest.

The product writer accepts `ProductionDecisionV2` only after
`CandidateSetCompletenessReceiptV1` matches the exact candidate IDs, count and
canonical order with `omitted_count_bound == 0`. The registered generator must
sign `decision_signing_payload_v2`; the signature is verified against the
writer's activated trust distribution before the durable append.

The existing `run_evaluated_shadow_v1` source consumer now holds
`LedgerWriter`, not `DurableLearningJournal`, and writes only
`AuthenticatedDecisionRecordV2`. It remains a qualification/shadow consumer,
not evidence of a live production deployment.

## Historical acknowledgement recovery

The authenticated terminal caller first binds the complete Outcome or CreditBatch
payload to its original evidence and predecessor, then asks the existing writer
for the exact committed acknowledgement. An expired signature may identify a
historical commit; it cannot append an absent fact, renew data eligibility or
redispatch a physical operation. Credit admission failure preserves the recovered
Outcome receipt. Changed payloads, signatures, stores or predecessors cannot
recover a different request. The active run/episode binding remains required.

`outcome_credit_v2` regressions include process exit after both commits, reopening
without the original writer, expired evidence, changed payloads and missing credit.
This is owner/facade recovery, not a claim that the default Agentd has persisted
its complete canonical handoff or every pending append identity.

## Outcomes and correction lineage

`AuthenticatedOutcomeRecordV2` persists independent observer controller,
credential, key, scope, authority epoch, delay profile, watermark state and
authentication digest. The ledger enforces:

- one root outcome lineage per episode;
- correction predecessor existence;
- same-episode predecessor;
- predecessor must be the current head;
- a revoked predecessor cannot be extended.

Because every correction points to the current head and record identities are
immutable, forks and cycles cannot be admitted. Only the current correction head
is active for downstream credit/dataset eligibility. Pending and censored states never become zero reward. Dataset derivation also
counts an authenticated Decision with no Outcome row at all as pending, so missing
observations cannot disappear from accounting.

## Atomic conserved credit

`CreditAllocationBatchRecordV2` is one durable event/frame. The ledger sorts
and deduplicates targets, requires an active terminal outcome with exactly the
same terminal value, requires allocator independence from generator and
observer identities/controllers, prevents a second committed credit batch for
the same outcome, and enforces

`sum(allocations) + conservation_residual == terminal_outcome`

in raw Q32 units before the append is prepared. Consumers therefore cannot
observe a partially committed conserved batch.

The old per-target V1 `CreditAssignment` remains readable for compatibility;
new product composition does not use it.

## Dataset freeze and unlearning

`LedgerWriter::freeze_dataset` does not accept caller-supplied source rows,
eligible frontier, correction cut, revocation cut or outcome watermark. It
rebuilds the current ledger, selects active authenticated decision/outcome/credit
facts for the requested objective, derives those frontiers and then emits the
self-verifying `DatasetSnapshotReceiptV3`. Immediately before final artifact
use, `LedgerWriter::revalidate_dataset_snapshot` verifies the historical receipt
and requires every frozen source digest to remain in the current canonical active
projection; later correction, revocation or unlearning therefore fails closed.

`LedgerWriter::append_unlearning` requires the exact `DatasetSnapshotReceiptV3`,
verifies its immutable identity at the historical producer authentication point,
proves that the receipt's source set contains the named canonical source event,
and persists both source-event and dataset digests in `UnlearningLineageEventV1`.
Replay rejects source-digest substitution. Appending the event logically revokes
the source record and the active projection then excludes causal descendants.
The stored `artifact_id` is only a handoff identity: `learning.artifacts` owns and
must verify dataset→artifact membership and descendant withdrawal/revocation.
This is logical non-resurrection lineage, not physical erasure, backup deletion
or proof of model unlearning.

## Trust distribution and witness

`LearningEvidenceVerifierV1` verifies Ed25519 signatures, scope/objective/epoch,
validity windows, role assignment, signer revocation and controller separation.

Product construction additionally requires `ActivatedLearningTrustV1`, created only after `activate_learning_trust` verifies a
`SignedLearningTrustDistributionV1` against a host-pinned `LearningTrustRootV1`.
The signed distribution binds scope, objective, authority epoch, signer/controller
identities, roles, key material, validity and revocation state. Distribution
generation advances exactly one step, effective time is monotonic and authority
epoch cannot roll back. The activated distribution has a content digest binding
its generation and verifier context.

`LedgerWitnessStore` is a separately locked append-only HEPTLW01 file. A
`LedgerWriter` does not acknowledge a newly appended ledger fact until the
corresponding witness frontier is synced. A ledger may lead the witness by only
one exact record during lost-acknowledgement reconciliation. Segmented rotation
is performed through `LedgerWriter::rotate_segment`. The host supplies an
authorized handle for the actual containing directory; the writer synchronizes
that directory after successor initialization and before advancing the witness
to the new topology.

The host still owns pinned-root provisioning/rotation ceremony, distribution transport,
trusted file and directory opening/identity, witness placement/isolation,
key-distribution transport, encryption and physical durability qualification.

## Canonical protocol compatibility

`src/protocol.rs` defines explicit Rust compatibility views using the exact
registered names `LearningDecisionV1`, `OutcomeReceiptV1`,
`CreditAssignmentReceiptV1`, `DatasetSnapshotV1` and `LearningEpisodeV1`.
JSON decoding rejects unknown fields and enforces the registered 256 KiB bound.
Adapters derive those views from stronger V2 durable facts; they do not turn a
legacy JSON object into authenticated V2 evidence.

## Rebuildable checkpoint/index

`LedgerIndexCheckpointV1` is a content-addressed acceleration artifact over an
anchored `LedgerSnapshot`. It binds record ID → sequence/event digest/activity,
current authenticated outcome heads and the revocation/unlearning frontier.
Verification fully rebuilds the checkpoint from canonical history. A mismatch
discards the index; the ledger remains the source of truth.

This supplies bounded lookup and verifiable index generation. It does not claim
constant-time full recovery or compaction: replay cost and in-memory indexes
still scale with retained history.

## Failure and retry rules

- semantic identity reuse with changed content conflicts;
- missing/stale/wrong-role authentication fails before causal append;
- generator/observer/allocator controller collisions fail closed;
- acknowledgement loss retries the original identity and semantic digest;
- a witness failure after ledger sync is indeterminate, never success;
- failed anchored reopen never silently retries unanchored;
- correction branches and stale predecessor corrections reject;
- pending/censored outcomes never become zero reward;
- source rows and dataset cuts are derived from current canonical state;
- logical unlearning cannot resurrect through the active projection;
- exported learning receipts grant no model/tool/effect/promotion authority.

## Qualification mapping

Focused tests include:

- `src/ledger_tests.rs`;
- `src/durable_tests.rs`;
- `src/segments_tests.rs`;
- `src/causal_v2_tests.rs`;
- `src/signed_evidence_tests.rs`;
- `src/production_tests.rs`;
- `src/witness_tests.rs`;
- `src/trust_distribution_tests.rs`;
- `src/protocol_tests.rs`;
- `src/checkpoint_tests.rs`.

Cross-crate composition is exercised by the evaluated-shadow tests and
`../hepta-intelligence/src/outcome_credit_v2.rs`, including correction and
partial-commit reconciliation. The executable
`examples/target_host_qualification.rs` measures exact-head append/rotation/
reopen/storage/RSS behavior on a named target host while keeping power-loss,
longitudinal-efficacy and activation claims false. Exact-head and synthetic-merge
CI remain source execution evidence; test source alone is not a pass receipt.

## Remaining external/product evidence

Repository source can implement the writer and a qualification consumer, but it
cannot self-issue:

1. daemon-owned invocation of the source-composed Decision and terminal-closure callsites using `LedgerWriter`;
2. the operator's current signer-distribution transport and key custody;
3. the physical placement/durability/isolation of ledger and witness files;
4. live independent terminal observations;
5. an actual run of the target-host harness on each selected deployment class, including latency, recovery, throughput, storage and RSS evidence;
6. independent semantic acceptance, canary, selection, promotion or release.

Those are separate evidence gates and must not be inferred from this source
mapping.

The consolidated writer retains root-signed live distribution rotation through `LedgerWriter::rotate_trust`; failed root/signature/monotonicity checks preserve the current distribution. Raw durable append is crate-private, and only the explicit `qualification-legacy-write` feature exposes historical fixture writes. `measure_ledger_recovery_work` is replay-validated capacity accounting, not a target-host latency or efficacy claim.
