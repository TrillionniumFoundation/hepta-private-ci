# `learning.eval` native implementation mapping

This file maps point, sequential, temporal, independent, recovery and product
evaluation design to concrete Rust symbols. Estimation, eligibility, selection,
activation and release remain separate authorities.

## Estimator primitives

| Evaluation operation | Native symbol | Source | Bound |
|---|---|---|---:|
| point IPS/SNIPS/DR and exact ESS | `estimate_ope` | `src/ope.rs` | `1,000,000` rows |
| conservative cluster intervals | `estimate_cluster_intervals` | `src/ope_confidence.rs` | point-estimator bound |
| finite-horizon history-conditioned PDIS/DR | `estimate_sequential` | `src/sequential.rs` | `4,096` trajectories / `65,536` steps / horizon `128` |
| one label-isolated temporal fold | `fit_temporal_fold` | `src/temporal_fold.rs` | `100,000` training or target rows |
| composed temporal holdout | `evaluate_temporal_holdout` | `src/temporal_evaluation.rs` | `16,384` held-out rows |

The stage bounds are intentionally different. The broad point-estimator ceiling
must not be presented as the composed temporal-pipeline capacity. These
primitives validate arithmetic, probability support, outcome watermarks, weight
limits, per-depth ESS, lineage separation and plan digests. They do not prove
causal exchangeability, authenticate a remote caller, select a candidate or
establish future-calendar efficacy.

## Product, admission and recovery closure

The normative API classification is in
[`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md), and the terminal-state
contract is in [`RECOVERY_CONTRACT.md`](RECOVERY_CONTRACT.md).

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| freeze V2 cross-fold + metric-role plan | `freeze_cross_fold_plan_v2` | `src/metric_roles.rs` | implemented plan-freeze surface |
| freeze product estimator mapping | `freeze_product_evaluation_plan_v1` | `src/product_runner.rs` | implemented product plan freeze |
| temporal product evaluation | `ProductEvaluationRunnerV1::evaluate_temporal_comparison` | `src/product_runner.rs` | implemented sealed source composition |
| signed product qualification | `ProductEvaluationRunnerV1::qualify_and_persist` | `src/product_runner.rs` | implemented source composition; audited wrapper required for production |
| audited product ingress | `AuditedProductEvaluationRunnerV1` | `src/audited_runner.rs` | implemented attempt + holdout + publication composition |
| sealed repository admission | `admit_repository_evaluation_v1` | `src/repository_admission.rs` | implemented closed Agentd/plasticity integration surface |
| signed V2 verification | `decide_with_signed_evidence_v2` | `src/signed_evaluation.rs` | crate-private primitive |
| signed V3 observed-time verification | `decide_with_signed_longitudinal_evidence_v3` | `src/longitudinal_time.rs` | crate-private primitive |
| durable attempt state | `EvaluationAttemptJournalV1` / `EvaluationAttemptCasStoreV1` | `src/attempt_journal.rs` | implemented CAS state machine; target store remains host-bound |
| idempotent publication | `ReconcilingQualificationEvidenceSinkV1` / `IdempotentQualificationEvidenceSinkV1` | `src/evidence_sink.rs` | implemented accepted-or-unknown reconciliation contract |
| single-host durable holdout owner | `DurableFinalHoldoutJournalV1` | `src/durable_holdout.rs` | cooperative/single-host compatibility |
| fenced holdout owner | `FencedFinalHoldoutOwnerV1` / `FinalHoldoutCasStoreV1` | `src/fenced_holdout.rs` | implemented canonical contended owner |
| locked event-log CAS | `LockedFileFinalHoldoutCasStoreV1` | `src/fenced_holdout_file.rs` | implemented cross-process backend |
| checkpoint/compaction CAS | `LockedCheckpointFinalHoldoutCasStoreV1` | `src/checkpoint_holdout_file.rs` | implemented full-checkpoint backend |
| trusted direct compatibility | `trusted_inprocess::decide_independently{,_v2}` | `src/lib.rs` | feature-gated; never production ingress |
| legacy threshold comparator | `trusted_inprocess::evaluate_legacy_inprocess_v1` | `src/lib.rs` | deprecated trusted-only compatibility |

## API boundary and registered callers

The raw V2/V3 decision functions are re-exported only as `pub(crate)`. The
external compile-fail fixture is
`qualification/compile-fail/learning-eval-private-api.rs`; the verifier is
`scripts/hepta-learning-eval-api-boundary.py`.

The closed repository caller inventory is:

| Consumer | Source | Surface consumed | Meaning |
|---|---|---|---|
| evaluated shadow | `../hepta-intelligence/src/evaluated_shadow.rs` | sealed `ProductQualificationReceiptV1` | terminal repository product-qualification consumer |
| Agentd | `../hepta-agentd/src/intelligence_evaluation.rs` | `RepositoryEvaluationAdmissionV1::Agentd` | request-bound signed eligibility only |
| governed plasticity | `../hepta-intelligence/src/plasticity_product.rs` | `RepositoryEvaluationAdmissionV1::Plasticity` | candidate-bound signed eligibility only |

Agentd and plasticity bind the exact consumer context before admission. Their
receipts have private seals and remain `DENY_ALL`; they cannot be interpreted as
final-holdout qualification. Adding a caller requires updating the machine map,
status manifest, compile matrix and closed-world API verifier.

## Holdout, attempt and publication semantics

`freeze_cross_fold_plan_v2` retains complete V1 lineage and holdout invariants
while binding preregistered metric roles and margins. Two to thirty-two folds are
canonicalized and checked for training/holdout leakage. The final holdout never
enters training and is covered exactly once.

`FencedFinalHoldoutOwnerV1` is the contended ownership boundary. A newer fence
generation takes over only through CAS while preserving the journal. An old
writer conflicts. An accepted-or-unknown store commit returns `Indeterminate`,
poisons the handle and requires reload/reconciliation.

`EvaluationAttemptJournalV1` binds one plan digest to one attempt ID. It records
pre-holdout rejection, consumed-without-receipt, holdout-CAS uncertainty,
temporal completion, qualification rejection, publication uncertainty and
published completion. A consumed or uncertain holdout cannot be silently retried.

`IdempotentQualificationEvidenceSinkV1` uses the temporal execution digest as
the idempotency key. Exact committed retries return the existing publication;
different semantics conflict. `ReconcilingQualificationEvidenceSinkV1` resolves
an accepted-but-response-lost write by lookup and otherwise preserves
`Indeterminate`.

## Checkpoint and compaction mapping

`LockedCheckpointFinalHoldoutCasStoreV1` stores a complete validated CAS record
in every checksummed frame. It enforces:

- lifetime OS-file exclusion;
- bounded file, frame, checkpoint and journal counts;
- semantic reconstruction of every stored plan;
- monotonic fence or exactly-one-record journal transitions;
- retained-anchor rollback rejection;
- truncated uncommitted-tail removal;
- accepted-or-unknown poisoning;
- fresh-file single-checkpoint compaction;
- sealed compaction receipts and storage metrics.

The ignored capacity qualification test materializes the maximum configured
`100,000` checkpoint generations, records file bytes and recovery milliseconds,
and verifies the declared `512 MiB` file ceiling. The target host must repeat the
profile on its actual storage stack; repository CI is not cross-host filesystem
qualification.

## Identity, causal and statistical obligations

`LearningEvidenceVerifierV1` verifies signed evidence against host-owned current
trust before accepting generator/evaluator/observer identities. Signing proves
that an authorized key attested bytes; it does not establish unbiased
measurement, honest controller registration, confidence coverage or learning
gain.

Causal identification remains conditional on consistency, support, correct
propensity, appropriate cluster independence and the declared confounding
assumptions. Unsupported assumptions produce insufficient evidence; an outcome
model cannot repair zero support.

Cluster and temporal receipts carry private integrity seals. The product runner
derives each `MetricGateV1` from sealed candidate/baseline intervals selected by
the preregistered metric-source contract. Callers cannot inject replacement
intervals.

## Target-host obligations

A target profile must name:

1. scheduler and immutable evaluation plan store;
2. final-holdout CAS, fence issuer and independently retained anchor;
3. evaluation-attempt CAS implementation;
4. idempotent qualification evidence owner;
5. authenticated dataset, outcome-observer and candidate manifests;
6. exact folds, nuisance runtime and resource measurements;
7. real future windows and independently identified snapshots where claimed;
8. retention, subgroup/privacy and unlearning evidence;
9. distinct semantic reviewer, selector, operator and release principals.

The required evidence bundle is specified in
`../../docs/modules/learning.eval/TARGET_HOST_ACCEPTANCE.md`. A virtual-clock
fixture cannot satisfy a future-calendar or longitudinal claim.

## Qualification mapping

Focused tests include:

- `src/lib_tests.rs`;
- `src/ope_tests.rs` and `src/ope_confidence_tests.rs`;
- `src/sequential_tests.rs`;
- `src/temporal_fold_tests.rs` and `src/temporal_evaluation_tests.rs`;
- `src/closure_tests.rs`;
- `src/durable_holdout_tests.rs`, `src/fenced_holdout_tests.rs` and
  `src/fenced_holdout_file_tests.rs`;
- `src/product_runner_tests.rs` and `src/longitudinal_time_tests.rs`;
- inline tests in `src/repository_admission.rs`, `src/evidence_sink.rs`,
  `src/attempt_journal.rs` and `src/checkpoint_holdout_file.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`. The API/resilience workflow
retains compile-fail, fault-injection, capacity and provenance evidence. These
are source facts, not target-host acceptance or release authority.
