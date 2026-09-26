# `learning.eval` native implementation mapping

This file maps point, sequential, temporal and independent evaluation design to
concrete Rust symbols. Estimation, evidence eligibility and artifact selection
remain separate authorities.

## Existing estimator primitives

| Evaluation operation | Native symbol | Source | Bound |
|---|---|---|---:|
| point IPS/SNIPS/DR and exact ESS | `estimate_ope` | `src/ope.rs` | `1,000,000` rows |
| conservative cluster intervals | `estimate_cluster_intervals` | `src/ope_confidence.rs` | point-estimator bound |
| finite-horizon history-conditioned PDIS/DR | `estimate_sequential` | `src/sequential.rs` | `4,096` trajectories / `65,536` steps / horizon `128` |
| one label-isolated temporal fold | `fit_temporal_fold` | `src/temporal_fold.rs` | `100,000` training or target rows |
| composed temporal holdout | `evaluate_temporal_holdout` | `src/temporal_evaluation.rs` | `16,384` held-out rows |

The stage bounds are intentionally different. The broad point-estimator ceiling
must not be presented as the composed temporal pipeline capacity.

Existing primitives validate deterministic arithmetic, probability support,
outcome watermarks, weight limits, per-depth ESS, lineage separation and exact
plan digests. They deliberately do not authenticate caller-supplied identities,
prove causal exchangeability, select a candidate or establish future-calendar
efficacy.

## Added implementation closure

The normative API classification is in
[`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md).

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| freeze complete V2 cross-fold + metric-role plan | `freeze_cross_fold_plan_v2` | `src/metric_roles.rs` | production plan-freeze surface |
| single-host durable holdout owner | `DurableFinalHoldoutJournalV1` | `src/durable_holdout.rs` | implemented; cooperative/single-host only |
| multi-writer fenced holdout owner | `FencedFinalHoldoutOwnerV1` / `FinalHoldoutCasStoreV1` | `src/fenced_holdout.rs` | implemented canonical owner |
| concrete locked-file CAS + anti-rollback recovery | `LockedFileFinalHoldoutCasStoreV1` / `FinalHoldoutCasAnchorV1` / `HoldoutFenceIssuerV1` | `src/fenced_holdout_file.rs`, `src/fenced_holdout.rs` | implemented cross-process backend |
| product preregistration/evaluation/qualification | `freeze_product_evaluation_plan_v1` / `ProductEvaluationRunnerV1` | `src/product_runner.rs` | implemented source product composition |
| signed independent verification primitive | `decide_with_signed_evidence_v2` | `src/signed_evaluation.rs` | crate-internal; invoked by product runner |
| signed observed-time longitudinal verification primitive | crate-internal `decide_with_signed_longitudinal_evidence_v3` | `src/longitudinal_time.rs` | crate-internal V3; invoked by product runner for `SystemLongitudinal` |
| trusted direct compatibility | `trusted_inprocess::decide_independently{,_v2}` | `src/lib.rs` | feature-gated; not production ingress |
| legacy threshold comparator | `trusted_inprocess::evaluate_legacy_inprocess_v1` | `src/lib.rs` | deprecated trusted-only compatibility |

`freeze_cross_fold_plan_v2` retains the complete V1 lineage and holdout
invariants while also binding preregistered metric roles and margins into the
frozen digest. Two to thirty-two folds are canonicalized and checked for
training/holdout leakage; the final holdout never enters training and is covered
exactly once. Local seals detect mutation but are not credentials.

`DurableFinalHoldoutJournalV1` persists the semantic journal under an
authorized regular file, file lock, synchronous writes and an independently
retained anchor. It is suitable only when the host guarantees one authoritative
namespace and cooperating local writers.

`FencedFinalHoldoutOwnerV1` is the canonical production boundary for contended
ownership. `LockedFileFinalHoldoutCasStoreV1` supplies a concrete locked-file
CAS/replay backend with a separately retained minimum anchor; alternate target
hosts may implement `FinalHoldoutCasStoreV1` with an equivalent linearizable
store. `HoldoutWriterFenceV1` binds owner, monotonic generation and
lease digest. A newer generation takes over only by CAS without rewriting
journal history; a stale owner then conflicts on its next write. An
accepted-or-unknown store commit returns `Indeterminate`, poisons the handle
and requires reload/reconciliation.

`ProductEvaluationRunnerV1::qualify_and_persist` invokes crate-internal `decide_with_signed_evidence_v2`, which authenticates the generator's frozen-plan
attestation and the evaluator's exact V2 request bytes against host-owned trust,
then verifies principal/key/credential/controller separation before invoking the
bound V2 statistical decision. `decide_with_signed_longitudinal_evidence_v3`
adds an independently signed observer and real observed-time window contract.
Synthetic future IDs cannot satisfy that stronger claim.

The output remains one of:

```text
EligibleForIndependentSelection
Ineligible
InsufficientEvidence
```

Even the first state has `DENY_ALL` authority. A separate selector must consume it together with all other gates. The repository's current consumer `codex-rs/hepta-intelligence/src/evaluated_shadow.rs::run_evaluated_shadow_v1` consumes the sealed `ProductQualificationReceiptV1` and does not re-run the low-level evaluator; that composition is still not activation, promotion or release.

## Identity, causal and statistical obligations

The default production closure does not trust caller-constructed identity fields. `LearningEvidenceVerifierV1` verifies signed evidence against host-owned current trust before the signed evaluation path accepts generator/evaluator identities. Direct identity-based evaluators are available only behind the explicit `trusted-inprocess-eval` compatibility feature.

Causal identification remains conditional on the frozen plan's assumptions:
consistency, support, correct propensity, appropriate cluster independence and
absence or bounded treatment of confounding. Unsupported assumptions produce
insufficient evidence; an outcome model cannot repair zero support.

Cluster and temporal estimator receipts now carry private integrity seals. `ProductEvaluationRunnerV1` derives each final `MetricGateV1` from the sealed candidate/baseline interval selected by the preregistered product metric-source contract; caller-supplied intervals are not part of this product path. Privacy review, change-point admission and real future-window collection remain external evidence obligations.

## Publication and recovery adapters

`src/product_publication.rs` prepares authenticated signing bytes but not receipts.
`../hepta-agentd/src/intelligence_evaluation_publication.rs` implements the concrete
sink over the existing daemon evidence endpoint. The evidence owner refreshes the
issuer after writer serialization. `src/product_recovery_tests.rs` covers local
crash/replay cuts, and `../hepta-agentd/tests/support/evaluation_publication.rs`
exercises the real daemon publication transport, restart and revocation.
The input provider, complete job scheduler and original-intent outbox remain
product integration obligations, not capabilities supplied by the test fixtures.
The isolated storage probe is `examples/fenced_holdout_probe.rs`.

## Product integration obligations

A product receipt must name:

1. the scheduler and immutable evaluation plan store;
2. the durable final-holdout-use registry, single-writer fence and
   canonical persistence/reload of frozen-plan and holdout-use receipts;
3. the authenticated dataset, outcome-observer and candidate manifests;
4. the exact fold assignments and nuisance-model runtime;
5. the target host, resource measurements and incomplete/censored counts;
6. future calendar windows and independently identified snapshots;
7. retention, subgroup/privacy and unlearning evidence;
8. the distinct selector, operator and release principals.

A fixture using synthetic future timestamps cannot satisfy the future-calendar
or longitudinal claim.

## Qualification mapping

Focused tests live in:

- `src/lib_tests.rs`;
- `src/ope_tests.rs` and `src/ope_confidence_tests.rs`;
- `src/sequential_tests.rs`;
- `src/temporal_fold_tests.rs` and `src/temporal_evaluation_tests.rs`;
- `src/closure_tests.rs`;
- `src/durable_holdout_tests.rs`, `src/fenced_holdout_tests.rs` and `src/fenced_holdout_file_tests.rs`;
- `src/product_runner_tests.rs` and `src/longitudinal_time_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.
