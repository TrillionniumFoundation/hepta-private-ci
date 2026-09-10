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

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| freeze complete cross-fold lineage | `freeze_cross_fold_plan` | `src/closure.rs` | implemented |
| record final holdout use | `FinalHoldoutRegistry::consume` | `src/closure.rs` | implemented |
| issue independent eligibility decision | `decide_independently` | `src/closure.rs` | implemented |

`freeze_cross_fold_plan` requires two to thirty-two folds. It canonicalizes and
deduplicates every principal, episode and window set; rejects training/holdout
leakage within a fold; prevents the final holdout from entering any training
set; prevents a holdout lineage from appearing in multiple folds; and requires
the final holdout window to be covered exactly once. Its v2 plan digest also
binds claim scope, candidate, baseline, objective, dataset, estimand, metric
identities/directions/safety floors, multiplicity, every fold model and
predictions digest, and the final-holdout window and byte digest. The returned
typed receipt carries a module-private integrity seal, so field mutation cannot
be reintroduced as an apparently frozen plan.

`FinalHoldoutRegistry::consume` accepts the sealed frozen-plan receipt rather
than a reusable plan name. It indexes both final-holdout byte digest and window
identity. Reusing one plan ID with changed claim scope, model, predictions,
lineage, candidate, objective, dataset, estimand, threshold or multiplicity is
an identity conflict. A different plan reusing either holdout identity is
rejected. A genuinely identical retry returns the original registry and use
digests even after unrelated registry growth. The returned use receipt is also
integrity-sealed. A future persistent host adapter must retain this state under
a single writer; the pure type does not itself prove durable exclusivity.

`decide_independently` consumes authenticated generator and evaluator identities
from `learning.ledger`, a sealed `CrossFoldPlanReceiptV1`, and the corresponding
sealed `HoldoutUseReceiptV1`. It rejects receipt mutation and every mismatch in
claim scope, candidate, baseline, objective, dataset, estimand, metric contract,
multiplicity, plan digest, holdout digest or holdout window before evaluating
results. It also rejects shared principal, credential-chain or signing-key
identity and validates expiry and authority epoch. It then intersects:

- the sealed frozen plan and its exact registered holdout-use receipt;
- estimate, support-audit and confidence receipt digests;
- candidate lower confidence bound versus baseline upper bound;
- every metric safety floor;
- multiplicity profile;
- snapshot and future-window coverage;
- retention receipts and unlearning receipt for system-longitudinal claims.

The output is one of:

```text
EligibleForIndependentSelection
Ineligible
InsufficientEvidence
```

Even the first state has `DENY_ALL` authority. A separate selector must consume
it together with all other gates.

## Identity, causal and statistical obligations

The native closure verifies authenticated identity fields but cannot create the
underlying trust. A product adapter must verify signatures and credential chains
against the current trust root before constructing `AuthenticatedPrincipalV1`.

Causal identification remains conditional on the frozen plan's assumptions:
consistency, support, correct propensity, appropriate cluster independence and
absence or bounded treatment of confounding. Unsupported assumptions produce
insufficient evidence; an outcome model cannot repair zero support.

Intervals and point estimates do not by themselves implement family-wide alpha
allocation, privacy review, change-point admission or future-window scheduling.
The independent decision requires their receipt digests, while the responsible
owners must provide the actual evidence.

## Product integration obligations

A product receipt must name:

1. the scheduler and immutable evaluation plan store;
2. the durable final-holdout-use registry and single-writer fence;
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
- `src/closure_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.
