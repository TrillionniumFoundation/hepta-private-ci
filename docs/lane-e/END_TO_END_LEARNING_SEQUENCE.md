# Lane E end-to-end learning sequences

This document names the linearization points and authority boundaries for the
four Lane E modules. It is an implementation map, not evidence that a product
caller, future-calendar outcome, independent operator or production deployment
exists.

## 1. Candidate decision to immutable dataset

```text
product host authenticates generator and immutable objective
  -> generator enumerates a bounded legal candidate set
  -> CandidateSetCompletenessReceiptV1 binds generator code, grammar,
     hard filters, deterministic truncation, canonical order and omission bound
  -> shadow or product policy emits one selected candidate and positive propensity
  -> LedgerWriter authenticates the generator and durably appends one immutable
     AuthenticatedDecisionV2 under the single learning.ledger owner
  -> effect owner or trusted observer authenticates independently from the generator
  -> AuthenticatedOutcomeV1 remains pending, censored or terminal according to
     OutcomeWatermarkV1; a Decision with no Outcome row is also counted pending
     at dataset freeze, and missing outcome never becomes zero
  -> LedgerWriter appends outcomes/corrections against the current linear
     predecessor head; stale branches and forks fail closed
  -> independent allocator finalizes one CreditAllocationBatchV1 whose
     allocations plus residual exactly equal the current terminal outcome, and
     LedgerWriter commits the whole batch as one durable event
  -> LedgerWriter derives source rows, eligible frontier, outcome watermark,
     correction cut and revocation/unlearning cut from canonical replay and emits
     the owner-native self-verifying DatasetSnapshotReceiptV3
  -> canonical cross-module publication uses the registered DatasetSnapshotV1
     compatibility adapter; V3 is not silently treated as an unregistered wire schema
```

Linearization rules:

1. Candidate completeness is checked before assignment and before the decision
   can enter an evaluable dataset.
2. A plain different string ID is insufficient for independence. Principal,
   credential-chain and signing-key identities must all differ and be current.
3. A terminal outcome requires an observed value and finalization time. A
   censored outcome requires a reason but no invented value.
4. Credit is published as a finalized batch. Individual allocations do not
   become authoritative before conservation succeeds.
5. Dataset freeze derives source rows and all cuts from current canonical replay;
   callers cannot self-report those frontiers. The owner-native V3 receipt is
   self-verifying, while the registered cross-module compatibility view remains
   `DatasetSnapshotV1` until a V3 wire schema is explicitly registered.

## 2. Dataset to operator and world-model candidates

```text
DatasetSnapshotReceiptV3
  -> independently recompute and verify the frozen DatasetSnapshotV2 identity
  -> require exact objective/dataset identity and exact source-record evidence
     equality before constructing an opaque verified training input
  -> fit_transition_model_verified_v2 builds an action-conditioned tabular
     baseline; relabelled duplicate evidence rejects before counting
  -> preserve the canonical DatasetSnapshotV1 exchange adapter and revalidate current objective, lineage and withdrawal state at final use
  -> unsupported state/action pairs return OOD instead of extrapolation
  -> validate_applicability_certificate performs structural checks only
  -> validate_applicability_with_signed_evidence_v2 additionally requires
     host-trusted generator/evaluator signatures and role/controller separation
  -> build_sensor_core deterministically selects a fixed farthest-point core
     and measures fill distance, separation radius and mesh ratio
  -> evaluate_bellman_reference requires a complete sensor/action grid and emits
     deterministic targets, greedy actions and action gaps
  -> verify_tabular_operator_plan_v2 binds exact frozen rows before
     fit_tabular_operator_verified_v2; canonical fit rejects duplicate evidence
  -> admit_operator_regularity performs structural regularity checks
  -> admit_operator_regularity_with_signed_evidence_v2 authenticates the exact
     assessment including dominant-component approval
  -> candidate bytes and the complete V2 manifest go to learning.artifacts
```

The existing `train` API is retained only as a compatibility alias for
`build_targets`. The direct fit APIs remain compatibility surfaces for already
trusted callers; new qualification code uses the receipt-bound V2 constructors.
An evaluator ID or credential digest alone is structural metadata, not authenticated
independence. Signed V2 admission authenticates the exact bytes but still does not
prove scientific validity, future efficacy or selection authority.

World-model predictions are always marked synthetic. They may support planning
or evaluation models, but they cannot become the independent factual outcome
that judges the same candidate.

## 3. Artifact publication and latest-head admission

```text
host authenticates a scoped withdrawal authority/domain/registry
  -> LearningArtifactManifestV2 binds bytes, datasets, complete lineage,
     predecessors, training code, runtime, device, objective, schema,
     normalization, compatibility, expiry and rollback predecessor
  -> admit_manifest_at_withdrawal_head_v3 binds the exact scoped withdrawal head
  -> ArtifactPublicationTransactionV1 begins at the exact V1 registry predecessor
  -> payload bytes are validated, created and synchronized
  -> transaction records PayloadDurable
  -> V1 compatibility registration is appended and its snapshot is durable
  -> transaction revalidates the live scoped withdrawal frontier, verifies the
     V1 projection and records RegistryDurable
  -> independent RegistryHeadWitnessV1 binds generation, predecessor head and
     authority epoch
  -> transaction revalidates the withdrawal frontier, verifies the exact witness
     receipt and records WitnessDurable
  -> final acknowledgement revalidates the current withdrawal frontier again and
     is permitted only from WitnessDurable
```

`DatasetWithdrawalScopeV1` binds `authority_domain_id + registry_id + scope_id`.
A scoped registry has a scope-specific genesis/head, and the scope digest is
included in V3 admission. An unscoped registry cannot issue a V3 admission and
cross-scope publication fails even when two scopes otherwise have equal event
content.

The V1 registry is a compatibility index. It cannot encode every V2 dataset,
lineage digest or predecessor. The publication transaction therefore keeps the
complete V3 admission as the authoritative V2 sidecar and checks only fields V1
can faithfully represent.

Readers must use a current independently retained head witness. A self-consistent
old snapshot is not sufficient. Generation rollback, authority-epoch rollback,
predecessor mismatch and expired current-head witnesses fail closed.

Publication is an ordered crash-recovery protocol rather than an assumed
distributed transaction. The host persists each transaction snapshot under its
writer fence before treating a phase as durable. A crash after payload
synchronization or registry publication cannot be relabelled acknowledged until
the exact witness phase is recovered and completed.

## 4. Evaluation and independent decision

```text
construct the complete EvaluationPlan before outcomes are inspected
  -> bind claim scope, candidate, baseline, objective, dataset, estimand,
     metric directions and safety floors, multiplicity, folds, final-holdout
     window and final-holdout digest
  -> freeze two or more cross-fold partitions into one sealed plan receipt
  -> every fold keeps training and holdout principal, episode and window
     lineages disjoint
  -> FinalHoldoutRegistry consumes that exact sealed plan receipt once
  -> fit nuisance model on training folds only
  -> compute OPE/sequential estimates and support diagnostics
  -> compute prespecified cluster intervals and multiplicity-adjusted evidence
  -> collect retention, subgroup, privacy and unlearning receipts
  -> decide_independently validates both receipt seals and their exact semantic
     binding, then verifies distinct principal, credential and signing key
  -> intersect candidate LCB versus baseline UCB, safety floors, support,
     multiplicity, snapshot count, future windows, retention and unlearning
  -> emit EligibleForIndependentSelection, Ineligible or InsufficientEvidence
```

An identical retry of the same frozen plan returns an idempotent holdout-use
receipt. Reusing a plan identity with changed semantics conflicts; a second plan
cannot reuse either the holdout digest or its final window. The deterministic
receipt seals detect in-process field mutation but are not signatures and do not
replace durable single-writer storage or authenticated issuer evidence.

`EligibleForIndependentSelection` deliberately grants no selection authority.
The evaluator cannot install, activate, merge, promote or release the artifact.

Resource ceilings are stage-specific:

| Stage | Bound |
|---|---:|
| Point OPE | `1,000,000` rows |
| Tabular temporal fold | `100,000` rows |
| Composed temporal holdout | `16,384` rows |
| Sequential evaluator | `4,096` trajectories / `65,536` steps |
| Sequential horizon | `128` |

A broad point-estimator bound must not be reused as the capacity claim for the
composed temporal pipeline.

## 5. Artifact lifecycle, load and rollback

```text
proposed -> trained -> evaluated -> shadow -> canary
         -> operator_accepted -> selected -> retired
any eligible pre-retirement state -> revoked
bounded early state -> quarantined
```

The producer may record training completion but cannot evaluate, accept or
select its own candidate. Each state change binds an actor credential, evidence,
authority epoch and time. Skipping mandatory states fails. New mutations
validate the actor at current time; historical recovery validates the same
credential at the immutable event occurrence time, so a credential expiring
after a valid event does not make old lifecycle state unrecoverable.

Selection is consumed by a different supervisor or selector trust domain. The
selector signs the artifact identity, exact authenticated CURRENT head/witness,
manifest lineage and payload bindings. `ArtifactSelectionVerifierV1` binds that
selector trust to the actual artifact-owner trust snapshot and rejects selector
keys reused by writer/head authority. Only then may
`record_verified_selection` persist the `OperatorAccepted -> Selected`
evidence and `load_selected_candidate` expose the exact immutable bytes.

A new process still revalidates CURRENT before each use. The old process retains
its immutable run snapshot. Rollback is a new independently signed selection of
an exact compatible predecessor; it is never implicit reuse of an expired grant
or stale backup marker. Revocation at a newer CURRENT head makes even a freshly
signed selection attempt fail before payload use. Canary, promotion and release
remain separately governed outcomes.

## 6. Correction, deletion and non-resurrection

```text
source owner supplies authenticated correction or unlearning authority
  -> for explicit unlearning, LedgerWriter verifies the exact historical
     DatasetSnapshotReceiptV3 and proves the named canonical source event is in it
  -> LedgerWriter persists source_event_digest + dataset_digest in UnlearningLineageV1
     and advances the correction/revocation cut without rewriting history
  -> artifact_id in the ledger event is only a handoff identity; learning.artifacts
     verifies the authoritative dataset→artifact relation
  -> scoped DatasetWithdrawalRegistry durably records the withdrawn dataset digest
     with a scope-bound canonical snapshot receipt
  -> all directly matching artifacts are revoked
  -> lineage eligibility makes descendants unavailable
  -> new artifact admission rejects every withdrawn dataset
  -> caches, indexes and projections invalidate by generation
  -> affected models are rebuilt without revoked inputs or remain revoked
  -> backup restore replays the current ledger and withdrawal frontiers before
     any restored bytes become readable
  -> independent unlearning receipt verifies zero resurrection
```

The persistent withdrawal registry closes the admission gap left by a
snapshot-local revocation batch: a later artifact cannot silently reintroduce an
already withdrawn dataset. Physical erasure, external caches and backup media
still require the responsible storage owner and independent evidence.

## 7. Crash matrix

Every state-changing adapter must test at least these boundaries. The
publication transaction has source regressions that recover from prepared,
payload-durable and registry-durable snapshots and prove that none can skip to
acknowledgement:

1. before local validation;
2. after validation but before durable write;
3. after payload or event synchronization but before registry publication;
4. after registry publication but before witness publication;
5. after witness publication but before producer acknowledgement;
6. after evaluation evidence publication but before independent decision;
7. after new-generation load but before route publication;
8. after route publication but before predecessor retirement.

Recovery uses the stable operation identity, semantic digest, exact predecessor
and current authority epoch. Unknown effects become pending, indeterminate or
quarantined; they are never relabelled success and never retried with changed
semantics.
