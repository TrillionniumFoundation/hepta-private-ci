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

## Production implementation closure

`PRODUCTION_CONTRACT.md` is normative for ingress. The raw semantic engines remain
available only for explicit trusted compatibility; they are not production
qualification entrypoints.

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| freeze preregistered cross-fold lineage + metric roles | `freeze_cross_fold_plan_v2` | `src/metric_roles.rs` | production-required |
| durably consume final holdout and mint proof | `DurableFinalHoldoutJournalV1::consume_proven` | `src/durable_holdout.rs` | production-required |
| signed independent qualification | `decide_with_signed_durable_evidence_v3` | `src/signed_evaluation.rs` | production-required for `Qualification` |
| signed durable observed-time longitudinal qualification | `decide_with_signed_durable_longitudinal_evidence_v4` | `src/longitudinal_time.rs` | production-required for `SystemLongitudinal` |

Compatibility-only semantic operations include `freeze_cross_fold_plan`,
`FinalHoldoutRegistry::consume`, `decide_independently`,
`decide_independently_v2`, signed V1/V2 and longitudinal V3. They remain useful
for deterministic composition/migration tests but cannot satisfy the production
contract by themselves.

`freeze_cross_fold_plan_v2` requires two to thirty-two folds and preregistered
metric-role contracts. It canonicalizes and deduplicates every principal,
episode and window set; rejects training/holdout leakage within a fold; prevents
the final holdout from entering any training set; prevents a holdout lineage
from appearing in multiple folds; and requires the final holdout window to be
covered exactly once. The frozen receipt binds claim scope, candidate and
baseline identities, objective, dataset, estimand, metric directions, roles,
margins/safety floors, multiplicity profile, final-holdout window and
final-holdout bytes. Its deterministic integrity seal detects post-freeze field
mutation; it is not a signature or issuer credential.

The in-memory `FinalHoldoutRegistry::consume` remains the semantic compatibility
implementation. Production uses `DurableFinalHoldoutJournalV1::consume_proven`:
it durably appends/replays the same semantic journal and returns a private-field
adapter-origin proof that binds the supplied storage namespace, immutable
journal record and holdout-use receipt. Exact retries are idempotent; semantic
mutation and holdout reuse are rejected. The host still owns authoritative-file
selection, independent anchor/currentness, rollback protection and multi-host
CAS/fencing when applicable.

`decide_independently*` remains the trusted in-process semantic engine. The
production signed V3/V4 entrypoints authenticate generator/evaluator evidence
against host-owned trust state, require the durable proof, reject shared
principal/credential/signing/controller identity, and then intersect:

- an integrity-checked frozen-plan receipt and the exact consumed
  holdout-use receipt bound to it;
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
- `src/closure_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.
