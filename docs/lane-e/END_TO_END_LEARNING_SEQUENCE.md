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
  -> learning.ledger appends the immutable decision under its single writer
  -> effect owner or trusted observer authenticates independently from the generator
  -> AuthenticatedOutcomeV1 remains pending, censored or terminal according to
     OutcomeWatermarkV1; missing outcome never becomes zero
  -> corrections name a predecessor and append new facts
  -> independent allocator finalizes one CreditAllocationBatchV1 whose
     allocations plus residual exactly equal the terminal outcome
  -> learning.ledger freezes DatasetSnapshotV2 against an exact ledger head,
     eligible frontier, outcome watermark, correction cut, revocation cut and
     inclusion policy
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
5. Dataset freeze sorts and deduplicates source record digests. The emitted
   digest is independent of caller ordering and immutable for the bound cuts.

## 2. Dataset to operator and world-model candidates

```text
DatasetSnapshotV2
  -> validate current objective, lineage and withdrawal state
  -> fit_transition_model builds an action-conditioned tabular baseline from
     independently observed rows
  -> unsupported state/action pairs return OOD instead of extrapolation
  -> validate_applicability_certificate admits only current, independently
     evaluated smooth-axis profiles with positive ellipticity and named fallback
  -> build_sensor_core deterministically selects a fixed farthest-point core
     and measures fill distance, separation radius and mesh ratio
  -> evaluate_bellman_reference requires a complete sensor/action grid and emits
     deterministic targets, greedy actions and action gaps
  -> optional learned implementations are compared with that reference
  -> admit_operator_regularity intersects rank, reconstruction gain,
     monotonicity, positivity, Hölder/Lipschitz residuals, OOD and the complete
     error-component budget
  -> candidate bytes and the complete V2 manifest go to learning.artifacts
```

The existing `train` API is retained only as a compatibility alias for
`build_targets`. It is a deterministic target builder, not proof that a learned
operator, neural network or production inference path exists.

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
  -> transaction verifies the V1 projection and records RegistryDurable
  -> independent RegistryHeadWitnessV1 binds generation, predecessor head and
     authority epoch
  -> transaction verifies the exact witness receipt and records WitnessDurable
  -> producer acknowledgement is permitted only from WitnessDurable
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

Selection is consumed by a different supervisor or selector. A new process
loads an exact manifest and payload against the current registry head and current
withdrawal frontier. The old process retains its immutable run snapshot.
Rollback is a new authorized transition to an exact compatible predecessor; it
is never an implicit reuse of an expired grant or a stale backup marker.

## 6. Correction, deletion and non-resurrection

```text
source owner appends correction or deletion tombstone
  -> learning.ledger advances the correction/revocation cut
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
