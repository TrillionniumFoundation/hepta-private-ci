# learning.eval production contract

This file is the normative public-surface and ownership contract for
`learning.eval`. The architectural guide, recovery contract, evidence-admission
notes, native mapping, Lane E matrix and execution dossier must not weaken this
contract.

## Authority boundary

An evaluation can establish eligibility for a later independent selector. It
never selects, activates, promotes or releases a candidate. Every evaluation,
admission, attempt and product receipt remains `AuthorityPosture::DENY_ALL`.

A production final-holdout caller enters through
`AuditedProductEvaluationRunnerV1`, which composes
`ProductEvaluationRunnerV1`, a durable attempt journal and an idempotent,
reconcilable evidence sink. Raw V2/V3 signed-decision functions are
crate-private. Asserted `AuthenticatedPrincipalV1` values are not external
authentication.

## API status

| Surface | Status | Permitted use |
|---|---|---|
| `AuditedProductEvaluationRunnerV1::{evaluate_temporal_comparison,qualify_and_persist}` | **Canonical product ingress** | Couples final-holdout evaluation, terminal attempt state and reconciled durable evidence publication |
| `ProductEvaluationRunnerV1` | Product composition primitive | Builds sealed temporal and qualification receipts; production callers wrap it with the audited runner |
| `admit_repository_evaluation_v1` | **Repository integration ingress** | Produces a sealed, consumer-bound `DENY_ALL` eligibility receipt for the closed Agentd/plasticity consumer set; not final-holdout qualification |
| `evaluation_signing_payload_v2` / `longitudinal_evaluation_signing_payload_v3` | Public signer contracts | External signers attest exactly the runner-derived bundle/timing bytes |
| `decide_with_signed_evidence_v2` / `decide_with_signed_longitudinal_evidence_v3` | **Crate-private verification primitives** | Invoked only inside `learning.eval`; external import is compile-fail qualified |
| `freeze_product_evaluation_plan_v1` | Production plan freeze | Freezes V2 metric roles, metric-to-estimator mapping and candidate/baseline temporal plan identities before holdout release |
| `FencedFinalHoldoutOwnerV1` + `FinalHoldoutCasStoreV1` | Required for contended ownership | Linearizable CAS, monotonic writer fencing and accepted-or-unknown handling |
| `LockedFileFinalHoldoutCasStoreV1` | Event-log backend | Concrete cross-process locked-file replay backend |
| `LockedCheckpointFinalHoldoutCasStoreV1` | Checkpoint/compaction backend | Full validated checkpoint frames, rollback anchor, bounded recovery metrics and single-checkpoint compaction |
| `EvaluationAttemptJournalV1` + `EvaluationAttemptCasStoreV1` | Required product attempt state | Prevents a consumed/unknown holdout from being silently retried |
| `IdempotentQualificationEvidenceSinkV1` | Required target evidence-store contract | Lookup, write-once semantics, conflict detection and accepted-or-unknown reconciliation |
| `DurableFinalHoldoutJournalV1` | Single-host/cooperative-owner compatibility | Local file durability only when the host guarantees exclusive namespace ownership |
| `trusted_inprocess::decide_independently{,_v2}` | Trusted-only | Explicit compatibility/test feature; never external qualification ingress |
| `trusted_inprocess::evaluate_legacy_inprocess_v1` | Deprecated / trusted-only | Legacy deterministic comparator; cannot be used as production qualification |

The `trusted_inprocess` module is absent from default builds and is available
only with the explicit `trusted-inprocess-eval` feature.

## Signed admission

For ordinary product qualification:

1. freeze the V2 plan, metric roles and metric-source mapping before holdout observation;
2. begin one durable attempt bound to the exact plan and pre-holdout state;
3. durably consume the exact frozen plan through the authoritative fenced holdout owner;
4. release the final holdout only after that consumption receipt exists;
5. derive candidate/baseline intervals from sealed estimator receipts over the same cohort;
6. authenticate the generator signature over the frozen plan digest;
7. authenticate the evaluator signature over the exact V2 evaluation payload;
8. verify current host-owned trust, scope, objective, epoch, lifetime and revocation;
9. verify generator/evaluator/observer separation by principal, credential chain, signing key and controller;
10. run the bound statistical, support, safety and claim-scope checks;
11. publish through the idempotent evidence owner and reconcile an uncertain response by lookup;
12. append the terminal attempt state before returning success or failure.

A `SystemLongitudinal` claim additionally requires V3 signed observer/time
evidence. Synthetic future IDs or virtual timestamps are never future-calendar
efficacy evidence.

## Repository-consumer admission

Agentd and governed plasticity need independently signed eligibility but do not
own the final-holdout product composition. They call
`admit_repository_evaluation_v1` with a final canonical consumer-binding digest.
The returned `RepositoryEvaluationAdmissionV1`:

- names the closed consumer kind (`Agentd` or `Plasticity`);
- binds evaluation, candidate, baseline, objective and dataset;
- retains decision, trust and authentication digests;
- has a private mutation-detecting seal;
- remains `DENY_ALL`;
- cannot be reinterpreted as `ProductQualificationReceiptV1`.

Adding another repository consumer is an ownership/API change and must update
the machine-readable caller inventory, compile matrix and closed-world checks.
No external crate may import the raw V2/V3 decision functions.

## Final-holdout ownership

### Single host

`DurableFinalHoldoutJournalV1` is valid only when the host provides an
exclusive authorized regular file, independently retained current anchor and
durable containing-directory semantics. Its file lock coordinates cooperating
local owners; it is not a distributed lock.

### Multiple processes or hosts

A contended deployment must implement `FinalHoldoutCasStoreV1` with linearizable
compare-and-swap semantics. The authoritative record binds scope, writer owner,
positive monotonic fence generation, lease digest, the complete replayable
journal and state digest.

A newer generation takes ownership only through CAS while preserving journal
history. Once takeover succeeds, an older writer must conflict. A write whose
commit status is unknown returns `Indeterminate`; the owner poisons the handle
and requires reload/reconciliation.

The repository provides two concrete single-filesystem backends:

- `LockedFileFinalHoldoutCasStoreV1`, an append-only fence/plan event log;
- `LockedCheckpointFinalHoldoutCasStoreV1`, an append-only sequence of complete
  validated CAS checkpoints with a compaction operation.

Both use lifetime OS locks, synchronous committed transitions and an
independently retained `FinalHoldoutCasAnchorV1` minimum. Cross-host use requires
a shared filesystem whose locking and fsync behavior has been independently
qualified as linearizable.

The checkpoint backend removes a truncated uncommitted tail only after the
retained minimum anchor can still be satisfied. Compaction writes one current
checkpoint to a fresh file and returns a sealed
`FinalHoldoutCompactionReceiptV1`. The host must durably install the new file and
anchor before retiring its predecessor.

## Attempt and publication recovery

`EvaluationAttemptJournalV1` gives a plan digest exactly one attempt identity.
An exact `Started` retry is idempotent before the holdout changes. The following
states forbid automatic re-execution:

- holdout consumed without a terminal temporal receipt;
- holdout consumption commit status indeterminate;
- temporal evaluation completed;
- qualification rejected;
- evidence publication indeterminate;
- publication completed.

`PublicationIndeterminate` may transition only to `Published` after a matching
committed record is read. `execution_digest` is the publication idempotency key.
The same key with different decision semantics conflicts. A missing record after
an uncertain write remains indeterminate.

The complete normative state machine and fault matrix are in
`RECOVERY_CONTRACT.md`.

## Canonical product evaluation chain

`ProductEvaluationRunnerV1` freezes the metric-to-estimator mapping into the
bound estimand, consumes the final holdout through
`FencedFinalHoldoutOwnerV1`, and only then invokes
`FinalHoldoutProviderV1::release_after_consumption`. Candidate and baseline
metric intervals are derived from sealed `TemporalEvaluationReceipt` and
`ClusterOpeEstimate` receipts; callers cannot submit replacement
`MetricGateV1` intervals.

`AuditedProductEvaluationRunnerV1` is the production composition around that
core. It requires a durable attempt CAS and wraps the target evidence store with
`ReconcilingQualificationEvidenceSinkV1`. Success is returned only after a
nonzero publication digest and a terminal `Published` attempt event exist. The
resulting `ProductQualificationReceiptV1` has a private integrity seal and binds
the candidate, evaluator, objective, dataset, snapshots, claim scope, signed
decision and durable publication.

## Canonical product consumer

The repository's current terminal qualification consumer is
`codex-rs/hepta-intelligence/src/evaluated_shadow.rs::run_evaluated_shadow_v1`.
It accepts only a sealed `ProductQualificationReceiptV1`, rechecks current trust,
dataset/objective/snapshot bindings and requires the evaluator to sign the
candidate bytes against that terminal receipt. It does not rerun low-level V2
admission.

Agentd and plasticity are separately registered consumers of
`RepositoryEvaluationAdmissionV1`; they are not terminal product-qualification
consumers. None of these paths claim runtime activation, target-host
qualification or production longitudinal efficacy.

## CI closure evidence

Repository-controlled qualification uses both:

- `Hepta Lane E gap closure`, for exact-head and ordered-parent synthetic-merge
  compilation, tests, coverage and cross-crate closure;
- `Hepta learning.eval API boundary`, for generated-status verification,
  external compile-fail proof, consumer compilation, fault injection,
  checkpoint capacity/compaction measurement and resilience provenance.

The exact immutable candidate must retain commit-addressed evidence binding at
least:

- source commit and tree;
- workflow run and build identities;
- `Cargo.lock`, this contract, `RECOVERY_CONTRACT.md`, `NATIVE_MAPPING.md`,
  `CURRENT_STATE.json` and traceability digests;
- measured line coverage with `>=85%` enforced by Lane E;
- signed qualification and evaluated-shadow E2E identities;
- raw V2/V3 external compile-fail output;
- stale-writer, commit-before-error, truncation, rollback and reconciliation
  fault logs;
- maximum configured checkpoint count, disk bytes and recovery time;
- evidence creation time and expiry where the artifact schema requires it.

Push evidence is provenance-attested by GitHub Actions. These are repository
source/CI facts only. They cannot self-issue live outcomes, real future-calendar
observations, independent semantic/operator acceptance, canary, selection,
promotion or release evidence.

## Completion states

`source_qualified_exact_head` may be claimed only when the exact head and its
ordered-parent synthetic merge pass Lane E and the API/resilience workflow
produces its commit-addressed artifact. `productionImplementation` remains false
until a named target host satisfies `TARGET_HOST_ACCEPTANCE.md` with
independently verifiable evidence. External gates remain separate and may not be
collapsed into source qualification.
