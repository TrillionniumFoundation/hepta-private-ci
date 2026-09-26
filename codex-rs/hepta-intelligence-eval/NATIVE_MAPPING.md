# `learning.eval` native implementation mapping

This file maps point, sequential, temporal, signed and product evaluation design
to concrete Rust symbols. Estimation, evidence eligibility, selection, activation
and release remain separate authorities. The normative surface and ownership
rules are in [`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md); generated source
truth and caller inventory are in
[`CURRENT_STATUS.json`](../../docs/modules/learning.eval/CURRENT_STATUS.json).

## Estimator primitives

| Evaluation operation | Native symbol | Source | Bound |
|---|---|---|---:|
| point IPS/SNIPS/DR and exact ESS | `estimate_ope` | `src/ope.rs` | `1,000,000` rows |
| conservative cluster intervals | `estimate_cluster_intervals` | `src/ope_confidence.rs` | point-estimator bound |
| finite-horizon history-conditioned PDIS/DR | `estimate_sequential` | `src/sequential.rs` | `4,096` trajectories / `65,536` steps / horizon `128` |
| one label-isolated temporal fold | `fit_temporal_fold` | `src/temporal_fold.rs` | `100,000` training or target rows |
| composed temporal holdout | `evaluate_temporal_holdout` | `src/temporal_evaluation.rs` | `16,384` held-out rows |

The stage ceilings are intentionally different. A point-estimator capacity is not
the capacity of the composed temporal pipeline. These functions validate bounded
deterministic arithmetic, support, outcome watermarks, weight limits, exact ESS,
lineage separation and canonical digests. They do not authenticate a caller,
prove causal exchangeability, select a candidate or establish future-calendar
efficacy.

## Public and internal operation map

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| freeze complete V2 cross-fold, metric-role and product-source plan | `freeze_cross_fold_plan_v2` / `freeze_product_evaluation_plan_v1` | `src/metric_roles.rs`, `src/product_runner.rs` | public production plan freeze |
| single-host cooperative holdout journal | `DurableFinalHoldoutJournalV1` | `src/durable_holdout.rs` | implemented compatibility owner |
| contended holdout owner | `FencedFinalHoldoutOwnerV1` / `FinalHoldoutCasStoreV1` | `src/fenced_holdout.rs` | canonical production ownership boundary |
| concrete locked-file CAS, anti-rollback recovery and copy-compaction | `LockedFileFinalHoldoutCasStoreV1::{create,recover,compact_into}` | `src/fenced_holdout_file.rs` | implemented cross-process backend |
| capacity state and compaction evidence | `LockedFileCasCapacityV1` / `LockedFileCasCompactionReceiptV1` | `src/fenced_holdout_file.rs` | public diagnostics and integrity-bound receipt |
| durable evaluation-attempt lifecycle | `LockedFileProductEvaluationAttemptJournalV1` | `src/attempt_journal.rs` | implemented locked-file journal |
| attempt-recorded product evaluation | `RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison` | `src/recorded_runner.rs` | canonical production evaluation ingress |
| product signed qualification and publication | `RecordedProductEvaluationRunnerV1::qualify_and_persist` | `src/recorded_runner.rs`, `src/product_runner.rs` | production qualification ingress |
| idempotent publication and accepted-unknown reconciliation | `ReconciledProductQualificationSinkV1` / `ProductQualificationPublicationStoreV1` | `src/reconciled_sink.rs` | canonical production publication adapter |
| consumer-bound signed eligibility | `admit_signed_eligibility_v2` | `src/signed_admission.rs` | public authority-free non-product admission |
| signed V2 decision primitive | `decide_with_signed_evidence_v2` | `src/signed_evaluation.rs` | crate-internal only |
| signed observed-time V3 decision primitive | `decide_with_signed_longitudinal_evidence_v3` | `src/longitudinal_time.rs` | crate-internal only |
| trusted direct compatibility | `trusted_inprocess::decide_independently{,_v2}` | `src/lib.rs` | feature-gated; never production ingress |
| legacy threshold comparator | `trusted_inprocess::evaluate_legacy_inprocess_v1` | `src/lib.rs` | deprecated trusted-only compatibility |
| storage recovery/capacity profile | `learning_eval_storage_profile` | `src/bin/learning_eval_storage_profile.rs` | qualification executable; no authority |

The raw `ProductEvaluationRunnerV1` remains public for bounded source
compatibility and tests. The production contract requires the recorded runner;
external qualification must demonstrate that the selected host does not bypass
the attempt journal.

## Frozen plan and estimator binding

`freeze_cross_fold_plan_v2` preserves complete V1 lineage and holdout invariants
while binding preregistered metric roles and margins. Two to thirty-two folds are
canonicalized and checked for training/holdout leakage. The final holdout never
enters training and is covered exactly once. `freeze_product_evaluation_plan_v1`
adds candidate and baseline temporal plan digests plus the registered IPS, SNIPS
or doubly-robust metric source to the estimand digest.

Candidate and baseline estimates are computed over the same authenticated cohort.
Private receipt seals bind the temporal and cluster results. Final `MetricGateV1`
values are derived from those receipts; callers cannot replace intervals after
seeing the holdout.

## Holdout ownership, recovery and compaction

`DurableFinalHoldoutJournalV1` is suitable only when a host guarantees one
exclusive local namespace. Contended composition uses
`FencedFinalHoldoutOwnerV1`, whose record binds scope, owner, monotonic fence,
lease digest, complete replayable journal and state digest. A newer generation
can take ownership only through CAS; stale writers fail on their next transition.
An accepted-or-unknown write returns `Indeterminate`, poisons the handle and
requires reload and reconciliation.

`LockedFileFinalHoldoutCasStoreV1` holds an OS file lock, appends checksummed
frames, fsyncs committed transitions and requires an independently retained
minimum anchor on recovery. `compact_into` never truncates the source. It writes a
new target, emits the current fence, replays every retained plan through the
normal CAS path and proves that final state and anchor are identical before
returning. Cross-host use still requires external evidence that the chosen shared
filesystem provides linearizable lock and fsync semantics.

## Attempt lifecycle

The production lifecycle is:

```text
HoldoutConsumed -> ComparisonSealed
HoldoutConsumed -> Failed
```

`RecordedProductEvaluationRunnerV1` commits `HoldoutConsumed` before forwarding
the provider's released observations. A terminal evaluation result is recorded
before returning. Exact retries are idempotent; a changed plan, changed holdout,
second conflicting terminal transition, truncated frame or concurrent second
writer fails closed. A consumed-but-failed attempt therefore remains auditable
and cannot be interpreted as permission to reuse the final holdout.

## Signed admission and product qualification

`decide_with_signed_evidence_v2` authenticates generator frozen-plan evidence and
evaluator exact-request bytes against host-owned trust. It verifies role, scope,
objective, epoch, lifetime, revocation and principal/key/credential/controller
separation before running the bound V2 statistical decision.
`decide_with_signed_longitudinal_evidence_v3` adds an independent observer and
observed-time contract. Both functions are crate-internal and compiler-negative
fixtures prove they cannot be imported from another crate.

`admit_signed_eligibility_v2` is the only public non-product facade over the V2
primitive. It requires a digest of the complete concrete consumer context and
returns a private-sealed, `DENY_ALL` receipt. Agentd binds run, objective,
snapshot, predecessor, candidate-set and selected-candidate context. Governed
plasticity binds proposal, candidate, artifact/evidence frontiers, dataset,
eligibility and generator context. Neither path consumes a final holdout or mints
a product qualification receipt.

Product qualification builds the bundle internally from the sealed product
execution, invokes V2 or V3 and publishes through
`ProductQualificationEvidenceSinkV1`. The canonical reconciled sink loads before
write, rejects semantic conflicts and reads back an indeterminate commit before
retrying. Success is reported only after the exact committed record is observed.

Every output remains one of:

```text
EligibleForIndependentSelection
Ineligible
InsufficientEvidence
```

Even the first state retains `DENY_ALL`. The repository product consumer
`codex-rs/hepta-intelligence/src/evaluated_shadow.rs::run_evaluated_shadow_v1`
accepts only a sealed `ProductQualificationReceiptV1`; it rechecks current trust,
dataset, candidate and evaluator bindings and does not rerun a low-level decision.

## Identity, causal and statistical obligations

A signature proves that an authorized key attested exact bytes. It does not prove
unbiased measurement, organizational independence, correct confidence coverage,
exchangeability, privacy or future learning gain. Causal identification remains
conditional on the frozen assumptions: consistency, positivity, propensity
validity, cluster/dependency validity and absent or bounded confounding. An
outcome model cannot repair zero support.

System-longitudinal source checks require independent snapshots, multiple future
windows, retention and unlearning receipts, but source fixtures and virtual time
are not real future-calendar evidence. The external target-host packet is defined
in `docs/modules/learning.eval/TARGET_HOST_QUALIFICATION.md`.

## Caller inventory

The generated source inventory recognizes exactly these repository consumers:

| Consumer | Path | Surface |
|---|---|---|
| agentd evaluation session | `codex-rs/hepta-agentd/src/intelligence_evaluation.rs` | `admit_signed_eligibility_v2` with request binding |
| governed plasticity proposal | `codex-rs/hepta-intelligence/src/plasticity_product.rs` | `admit_signed_eligibility_v2` with proposal binding |
| evaluated shadow | `codex-rs/hepta-intelligence/src/evaluated_shadow.rs` | sealed `ProductQualificationReceiptV1` |

`scripts/hepta-learning-eval-status.py` fails if another Rust crate refers to the
crate-internal V2/V3 decision symbols.

## Qualification mapping

Core tests remain in:

- `src/ope_tests.rs`, `src/ope_confidence_tests.rs`, `src/sequential_tests.rs`;
- `src/temporal_fold_tests.rs`, `src/temporal_evaluation_tests.rs`;
- `src/closure_tests.rs`, `src/longitudinal_time_tests.rs`;
- `src/durable_holdout_tests.rs`, `src/fenced_holdout_tests.rs` and
  `src/fenced_holdout_file_tests.rs`;
- `src/product_runner_tests.rs` and `src/signed_qualification_e2e_tests.rs`;
- inline tests in `signed_admission.rs`, `reconciled_sink.rs`,
  `attempt_journal.rs` and the compaction module.

`scripts/hepta-learning-eval-api-surface.sh` supplies compiler-positive and
compiler-negative API fixtures. `scripts/hepta-learning-eval-faults.sh` runs the
ack-loss, conflict, truncation, second-writer, stale-writer, unknown-commit,
backup-rollback and compaction matrix. `learning_eval_storage_profile` records
attempt write/recovery and holdout takeover/compaction/recovery measurements.

Cross-crate composition remains exercised by
`hepta-shadow-qualification/src/lane_e_closure_tests.rs`. The focused
`Hepta learning.eval convergence` workflow enforces `>=85%` measured line
coverage and retains commit-addressed source evidence. The Lane E workflow
independently qualifies the exact head and ordered-parent synthetic merge.

## Remaining external gates

No source or CI artifact self-issues:

1. selected-host authentication and durable namespace binding;
2. cross-host filesystem qualification when applicable;
3. real future-calendar outcomes and independent observation provenance;
4. retention, change-point, power, subgroup/privacy and unlearning evidence;
5. independent semantic/operator acceptance;
6. selection, canary, promotion, activation or release authorization.

Those states remain false in `CURRENT_STATUS.json` until an externally issued,
exact-candidate packet passes `scripts/hepta-learning-eval-target-host.py`.
