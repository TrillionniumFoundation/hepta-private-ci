# `learning.eval` native implementation mapping

This file maps point, cluster, sequential, temporal, cross-fold and independent evaluation to concrete Rust symbols. Estimation, eligibility, selection and release remain separate authorities.

## Estimator and composition surface

| Operation | Native symbol | Source | Bound / state |
|---|---|---|---|
| point IPS/SNIPS/DR | `estimate_ope` | `src/ope.rs` | 1,000,000 rows |
| cluster-aware intervals | `estimate_cluster_intervals` | `src/ope.rs` | point profile |
| finite-horizon PDIS/DR | `estimate_sequential` | `src/sequential.rs` | 4,096 trajectories / 65,536 steps / horizon 128 |
| label-isolated temporal fold | `fit_temporal_fold` | `src/temporal_fold.rs` | 100,000 training or target rows |
| composed temporal holdout | `evaluate_temporal_holdout` | `src/temporal_evaluation.rs` | 16,384 held-out rows |
| complete cross-fold freeze | `freeze_cross_fold_plan` | `src/closure.rs` | implemented |
| pure final-holdout anti-reuse | `FinalHoldoutRegistry::consume` | `src/closure.rs` | retained |
| predecessor-bound journal consume | `FinalHoldoutJournalV1::consume` | `src/holdout_journal.rs` | implemented |
| deterministic journal reopen | `FinalHoldoutJournalV1::from_snapshot` | `src/holdout_journal.rs` | implemented |
| independent eligibility | `decide_independently` | `src/closure.rs` | implemented |

The stage bounds are intentionally different. A broad point-estimator ceiling is not the capacity claim for temporal or sequential composition.

## Frozen plan and final holdout

`freeze_cross_fold_plan` requires two to thirty-two folds and disjoint training/holdout principal, episode and window lineages. It binds claim scope, candidate, baseline, objective, dataset, estimand, metric contract, multiplicity and final-holdout identity. Its unkeyed seal detects mutation but is not issuer authentication.

`FinalHoldoutRegistry::consume` prevents plan semantic mutation and reuse of either holdout digest or final window. `FinalHoldoutJournalV1` adds an expected-head CAS contract, canonical record chain, exact idempotent retry and deterministic snapshot replay. A product host persists the snapshot under an exclusive writer, authenticates the scheduler and validates the replayed head before readiness.

## Independent decision

`decide_independently` verifies generator/evaluator identity separation and exact frozen-plan/holdout-use binding, then intersects superiority intervals, safety floors, support, multiplicity profile, snapshots, future windows, retention and unlearning. `EligibleForIndependentSelection` still has deny-all authority and is not selection.

Causal claims remain conditional on support, consistency, propensity correctness, appropriate cluster independence and confounding assumptions. Unsupported assumptions yield insufficient evidence. Synthetic model predictions and internal utility are not independent task outcomes.

## Product obligations

A product receipt names the scheduler, immutable plan store, persistent holdout journal and writer fence, authenticated dataset/outcomes/manifests, fold assignments and nuisance runtime, target-host measurements, real future windows, retention/privacy/unlearning evidence and separate selector/operator/release principals.

## Qualification mapping

Focused tests live in `src/ope_tests.rs`, `src/ope_confidence_tests.rs`, `src/sequential_tests.rs`, `src/temporal_fold_tests.rs`, `src/temporal_evaluation_tests.rs`, `src/closure_tests.rs` and `src/holdout_journal.rs`. Cross-crate composition and public linkage are compiled by `hepta-shadow-qualification`. Exact mappings are in `../../qualification/lane-e/TEST_TRACEABILITY.json`.
