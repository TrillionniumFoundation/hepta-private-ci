# `learning.eval` native implementation mapping

This file maps point, sequential, temporal and independent evaluation design to
concrete Rust symbols. Estimation, evidence eligibility and artifact selection
remain separate authorities. Repository-controlled qualification status is owned
by `../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`; this mapping cannot
upgrade product composition, future-calendar evidence, acceptance or release.

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
| freeze complete cross-fold lineage | `freeze_cross_fold_plan` / `freeze_cross_fold_plan_v2` | `src/closure.rs` | implemented |
| record in-memory final holdout use | `FinalHoldoutRegistry::consume` | `src/closure.rs` | implemented |
| persist final holdout semantic journal | `DurableFinalHoldoutJournalV1` | `src/durable_holdout.rs` | implemented |
| couple journal success to independent durable anchor | `DurableFinalHoldoutOwnerV1<S>` | `src/host_holdout.rs` | implemented source contract |
| issue independent eligibility decision | `decide_independently` / `decide_independently_v2` | `src/closure.rs` | implemented |
| authenticate observed longitudinal timing | `decide_with_signed_longitudinal_evidence_v3` | `src/longitudinal_time.rs` | implemented |
| bind external preregistration/collection/clock provenance | `decide_with_signed_longitudinal_evidence_v4` | `src/longitudinal_provenance.rs` | implemented source contract |

`freeze_cross_fold_plan` requires two to thirty-two folds. It canonicalizes and
deduplicates every principal, episode and window set; rejects training/holdout
leakage within a fold; prevents the final holdout from entering any training
set; prevents a holdout lineage from appearing in multiple folds; and requires
the final holdout window to be covered exactly once. The frozen receipt also
binds claim scope, candidate and baseline identities, objective, dataset,
estimand, metric direction and safety-floor contract, multiplicity profile,
final-holdout window and final-holdout bytes. Its deterministic integrity seal
detects post-freeze field mutation; it is not a signature or issuer credential.

`FinalHoldoutRegistry::consume` accepts only the typed sealed frozen-plan
receipt. An exact retry of the identical plan is idempotent. Reusing the same
plan identity with changed semantics conflicts, while a different plan using
either the same final-holdout digest or the same final-holdout window is
rejected. The emitted holdout-use receipt binds the complete plan semantics,
registry state and use digest and carries its own deterministic integrity seal.
The pure type and unkeyed seals alone do not prove durable exclusivity or
authenticated origin.

`DurableFinalHoldoutJournalV1` persists the semantic journal under a locked,
synced append protocol and recovers only against an independently retained
minimum anchor. `DurableFinalHoldoutOwnerV1<S>` strengthens the product-facing
composition contract: the host provides a `HoldoutAnchorStoreV1`, and a newly
recorded consume is not exposed as successful until that independent store
advances from the expected anchor to the next anchor with durable compare-and-
store semantics. An unavailable, conflicting or indeterminate anchor commit
fences the owner. Recovery may advance an acknowledged prefix to the replayed
head, but a nonempty journal with no independently retained anchor is not
silently adopted. This source contract still cannot prove that a concrete host
anchor store is independent, authenticated, durable or current; those facts are
qualification evidence supplied by the product host.

`decide_independently` consumes authenticated generator and evaluator identities
from `learning.ledger`. It rejects shared principal, credential-chain or
signing-key identity and validates expiry and authority epoch. It then
intersects:

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

V3 longitudinal admission authenticates exact observed-window bytes, an
independent observer and trusted current-time bounds. V4 additionally requires
three distinct nonzero external receipt digests: frozen-plan preregistration,
actual outcome collection provenance and trusted-clock attestation. Those
digests enter both observer/evaluator signing paths and the final authentication
digest. V4 gives the qualification plane concrete references to check; it does
not let a repository fixture certify that wall-clock time elapsed or that a live
collector was independent.

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
2. the `DurableFinalHoldoutOwnerV1` caller, the concrete independent
   `HoldoutAnchorStoreV1`, its single-writer/CAS fence, authenticated namespace,
   directory durability and canonical persistence/reload of frozen-plan and
   holdout-use receipts;
3. the authenticated dataset, outcome-observer and candidate manifests;
4. the exact fold assignments and nuisance-model runtime;
5. the target host, resource measurements and incomplete/censored counts;
6. real future calendar windows and independently identified snapshots;
7. retention, subgroup/privacy and unlearning evidence;
8. distinct preregistration, collection and trusted-clock receipts for V4
   longitudinal admission;
9. the distinct selector, operator and release principals.

A fixture using synthetic future timestamps cannot satisfy the future-calendar
or longitudinal claim. The source can validate the shape and signatures of V4
provenance references but cannot self-issue production provenance.

## Qualification mapping

Focused tests live in:

- `src/lib_tests.rs`;
- `src/ope_tests.rs` and `src/ope_confidence_tests.rs`;
- `src/sequential_tests.rs`;
- `src/temporal_fold_tests.rs` and `src/temporal_evaluation_tests.rs`;
- `src/closure_tests.rs`;
- `src/durable_holdout_tests.rs` and `src/host_holdout.rs`;
- `src/longitudinal_time_tests.rs` and `src/longitudinal_provenance.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`. Exact-head and ordered-
parent synthetic-merge runs retain source-only qualification receipts from
`.github/workflows/hepta-lane-e-gap-closure.yml`; those artifacts explicitly do
not prove product execution, future-calendar evidence, independent acceptance
or release.
