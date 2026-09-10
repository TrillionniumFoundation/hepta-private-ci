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
host reserves a create-only artifact identity
  -> payload bytes are written and synchronized
  -> LearningArtifactManifestV2 binds bytes, datasets, complete lineage,
     predecessors, training code, runtime, device, objective, schema,
     normalization, compatibility, expiry and rollback predecessor
  -> DatasetWithdrawalRegistry is checked before admission
  -> registry event is staged against the exact predecessor head
  -> registry snapshot is durably published
  -> independent RegistryHeadWitnessV1 binds generation, predecessor head and
     authority epoch
  -> producer is acknowledged only after the witness is durable
```

Readers must use a current independently retained head witness. A self-consistent
old snapshot is not sufficient. Generation rollback, authority-epoch rollback,
predecessor mismatch and expired witnesses fail closed.

Payload publication and registry publication are a bounded saga rather than an
assumed distributed transaction. A crash after payload synchronization but
before registry publication leaves an orphan candidate. It does not create a
selected artifact. Orphan collection requires a separately fenced retention
operation and must not delete bytes referenced by any current or historical
registry head.

## 4. Evaluation and independent decision

```text
freeze CrossFoldPlanV1 before final outcomes are inspected, binding claim scope,
  candidate, baseline, objective, dataset, estimand, metric contracts,
  multiplicity, fold lineages, model/prediction digests and final-holdout identity
  -> freeze_cross_fold_plan emits a sealed deny-all plan receipt
  -> FinalHoldoutRegistry::consume records that exact semantic receipt once by
     plan ID, holdout byte digest and holdout window ID
  -> identical retries preserve the original registry/use receipt; same-ID drift
     conflicts and another plan reusing either holdout identity is rejected
  -> every fold keeps training and holdout principal, episode and window
     lineages disjoint
  -> fit nuisance model on training folds only
  -> compute OPE/sequential estimates and support diagnostics
  -> compute prespecified cluster intervals and multiplicity-adjusted evidence
  -> collect retention, subgroup, privacy and unlearning receipts
  -> decide_independently consumes both sealed receipts and verifies distinct
     principal, credential and signing key
  -> intersect candidate LCB versus baseline UCB, safety floors, support,
     multiplicity, snapshot count, future windows, retention and unlearning
  -> emit EligibleForIndependentSelection, Ineligible or InsufficientEvidence
```

Caller booleans such as “plan frozen” or “holdout unused” are not evidence. The
independent decision path accepts only a receipt emitted for the exact frozen
analysis identity. Receipt integrity is a source-level construction boundary;
durable single-writer storage and external authentication remain host duties.

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
authority epoch and time. Skipping mandatory states fails.

Selection is consumed by a different supervisor or selector. A new process
loads an exact manifest and payload against the current registry head and current
withdrawal frontier. The old process retains its immutable run snapshot.
Rollback is a new authorized transition to an exact compatible predecessor; it
is never an implicit reuse of an expired grant or a stale backup marker.

## 6. Correction, deletion and non-resurrection

```text
source owner appends correction or deletion tombstone
  -> learning.ledger advances the correction/revocation cut
  -> DatasetWithdrawalRegistry durably records the withdrawn dataset digest
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

Every state-changing adapter must test at least these boundaries:

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
