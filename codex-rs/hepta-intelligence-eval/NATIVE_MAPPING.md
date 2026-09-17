# `learning.eval` native implementation mapping

This file maps point, sequential, temporal and independent evaluation design to
concrete Rust symbols. Estimation, evidence eligibility and artifact selection
remain separate authorities. The canonical current-state projection is
[`docs/modules/learning.eval/STATUS.json`](../../docs/modules/learning.eval/STATUS.json);
this mapping explains implementation mechanics and does not widen that status.

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
| semantic final-holdout registry | `FinalHoldoutRegistry::consume` | `src/closure.rs` | implemented |
| durable final-holdout journal | `DurableFinalHoldoutJournalV1::consume` | `src/durable_holdout.rs` | implemented |
| product-composed temporal execution | `ProductEvaluationRunnerV1::evaluate_temporal_candidate` | `src/product_runner.rs` | implemented, target host unproved |
| product-composed signed qualification | `ProductEvaluationRunnerV1::qualify_candidate` | `src/product_runner.rs` | implemented, target host unproved |
| independent eligibility decision | `decide_independently` / signed V2/V3 adapters | `src/closure.rs`, `src/signed_evaluation.rs`, `src/longitudinal_time.rs` | implemented |

`freeze_cross_fold_plan` requires two to thirty-two folds. It canonicalizes and
deduplicates every principal, episode and window set; rejects training/holdout
leakage within a fold; prevents the final holdout from entering any training
set; prevents a holdout lineage from appearing in multiple folds; and requires
the final holdout window to be covered exactly once. The frozen receipt binds
claim scope, candidate and baseline identities, objective, dataset, estimand,
metric direction and safety-floor contract, multiplicity profile,
final-holdout window and final-holdout bytes. Its deterministic integrity seal
detects post-freeze field mutation; it is not a signature or issuer credential.

`DurableFinalHoldoutJournalV1` persists the semantic registry under an advisory
exclusive lock and synchronized journal. `ProductEvaluationRunnerV1` composes
that journal with the host-owned `HoldoutAnchorStoreV1` currentness contract.
The confirmatory execution order is fixed:

1. validate frozen-plan, observed holdout, objective, multiplicity and window binding;
2. require the independently retained anchor to equal the journal anchor;
3. durably consume and synchronize the final-holdout use receipt;
4. compare-and-swap the independently retained current anchor;
5. only then evaluate held-out outcomes;
6. poison the runner after an indeterminate anchor commit until explicit recovery.

An exact retry of an identical consumed plan is idempotent. Semantic mutation,
holdout digest/window reuse and stale external currentness are rejected. The
test-only in-memory anchor implementation is not production evidence. A target
host must provide an independently retained `HoldoutAnchorStoreV1`; a witness
colocated with a restorable journal backup does not establish independent
currentness merely because it implements the trait.

`ProductEvaluationRunnerV1::qualify_candidate` binds the exact frozen plan,
consumed holdout-use receipt, temporal evaluation identity, estimate/support/
confidence evidence and multiplicity to signed independent evidence. Ordinary
qualification uses the signed V2 path. A system-longitudinal claim can only use
the V3 observed-time path; synthetic timestamps cannot substitute for real
future-calendar evidence. All resulting product evaluation and qualification
receipts retain `DENY_ALL` authority.

## Identity, causal and statistical obligations

The native closure verifies authenticated identity fields but cannot create the
underlying trust. A product host must verify signatures and credential chains
against the current trust root before constructing authenticated principals.
The host must also prove scheduler/access separation: library ordering cannot
prove that a malicious process with direct access to final outcomes did not
inspect them before invoking the runner.

Causal identification remains conditional on the frozen plan's assumptions:
consistency, support, correct propensity, appropriate cluster independence and
absence or bounded treatment of confounding. Unsupported assumptions produce
insufficient evidence; an outcome model cannot repair zero support.

Intervals and point estimates do not by themselves implement privacy review,
change-point admission, external future-window scheduling or independent
operator acceptance. The responsible owners must supply those facts.

## Product integration obligations

The source-composed runner closes the repository-owned sequencing and durable
anchor contract, but production target-host evidence must still name and prove:

1. the scheduler, immutable evaluation-plan store and access boundary;
2. the concrete independently retained `HoldoutAnchorStoreV1` implementation,
   its single-writer/CAS fence and backup independence;
3. authenticated dataset, outcome-observer and candidate manifests;
4. exact fold assignments and nuisance-model runtime;
5. target-host resource measurements and incomplete/censored counts;
6. real future calendar windows and independently identified snapshots;
7. retention, subgroup/privacy and unlearning evidence;
8. distinct selector, operator and release principals.

The Lane-E workflow emits exact-head and synthetic-merge JSON evidence artifacts
only after its preceding source checks pass. Those artifacts prove source and
product-adapter execution in CI; they explicitly set production target-host,
future-calendar, independent acceptance, activation and release claims to
false.

## Qualification mapping

Focused tests live in:

- `src/lib_tests.rs`;
- `src/ope_tests.rs` and `src/ope_confidence_tests.rs`;
- `src/sequential_tests.rs`;
- `src/temporal_fold_tests.rs` and `src/temporal_evaluation_tests.rs`;
- `src/closure_tests.rs`;
- `src/product_runner_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`. Current status and the
remaining external evidence gates are canonicalized in
`../../docs/modules/learning.eval/STATUS.json`.
