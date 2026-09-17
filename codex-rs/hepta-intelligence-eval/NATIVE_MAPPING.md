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
plan digests. They deliberately do not create trusted caller identities, prove
causal exchangeability, select a candidate or establish future-calendar
efficacy.

## Implemented closure and evidence admission

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| freeze complete cross-fold lineage | `freeze_cross_fold_plan` / `freeze_cross_fold_plan_v2` | `src/closure.rs` | implemented |
| record semantic final-holdout use | `FinalHoldoutRegistry::consume` / `FinalHoldoutJournalV1::consume` | `src/closure.rs`, `src/holdout_journal.rs` | implemented |
| persist/recover final-holdout use | `DurableFinalHoldoutJournalV1::{create,recover,consume}` | `src/durable_holdout.rs` | implemented owner adapter |
| authenticate independently retained holdout anchor | `authenticate_holdout_anchor_v1` / `recover_with_authenticated_holdout_anchor_v1` | `src/authenticated_holdout.rs` | implemented admission boundary |
| issue independent eligibility decision | `decide_independently` / `decide_independently_v2` | `src/closure.rs` | implemented |
| authenticate generator/evaluator decision evidence | `decide_with_signed_evidence_v1` / `decide_with_signed_evidence_v2` | `src/signed_evaluation.rs` | implemented |
| admit observed future-calendar windows | `decide_with_signed_longitudinal_evidence_v3` | `src/longitudinal_time.rs` | implemented evidence gate |

`freeze_cross_fold_plan` requires two to thirty-two folds. It canonicalizes and
deduplicates every principal, episode and window set; rejects training/holdout
leakage within a fold; prevents the final holdout from entering any training
set; prevents a holdout lineage from appearing in multiple folds; and requires
the final holdout window to be covered exactly once. The frozen receipt also
binds claim scope, candidate and baseline identities, objective, dataset,
estimand, metric direction and safety-floor contract, multiplicity profile,
final-holdout window and final-holdout bytes. Its deterministic integrity seal
detects post-freeze field mutation; it is not a signature or issuer credential.

`FinalHoldoutRegistry::consume` and `FinalHoldoutJournalV1::consume` enforce the
semantic one-use rule. An exact retry of the identical plan is idempotent.
Reusing the same plan identity with changed semantics conflicts, while a
different plan using either the same final-holdout digest or the same
final-holdout window is rejected.

`DurableFinalHoldoutJournalV1` is now the repository-owned durable adapter. It
requires an authorized regular file, a nonzero namespace binding, exclusive
cooperating-writer file locking, bounded deterministic frames, replay validation
and synchronous writes. Recovery never silently recreates or truncates damaged
state and requires an independently retained minimum anchor. The host still owns
directory durability, the independently retained current anchor, trust and
revocation distribution, and the product scheduler. A file lock cannot protect
against a hostile filesystem or a copied store plus a rolled-back external
anchor.

`authenticate_holdout_anchor_v1` closes the source-level authenticated-origin
edge for that external anchor: a trusted `Observer` signs the exact storage
binding, sequence and head; admission uses host-owned `LearningEvidenceVerifierV1`
trust and a host-owned minimum-issued-at watermark. The freshness watermark is
not derived from the submitted witness. `recover_with_authenticated_holdout_anchor_v1`
refuses a zero bootstrap anchor; initialization stays explicit. The host must
still persist the latest anchor witness and freshness watermark outside the
journal before releasing confirmatory labels or acknowledging use externally.

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

Qualification-scoped external calls use the signed admission surfaces.
`decide_with_signed_evidence_v1/v2` verifies generator and evaluator signatures
against host-owned trust state. `decide_with_signed_longitudinal_evidence_v3`
additionally requires an independent trusted observer to sign exact observed
Unix-microsecond windows, source cuts, frozen plan, objective, dataset and the
host-preregistered minimum duration. Windows must occur after freezing, be
non-overlapping, have observations, use distinct source cuts and end before both
the observer attestation and trusted current time. A virtual-clock fixture can
test these rules but cannot establish that real calendar time elapsed.

The output of independent evaluation is one of:

```text
EligibleForIndependentSelection
Ineligible
InsufficientEvidence
```

Even the first state has `DENY_ALL` authority. A separate selector must consume
it together with all other gates.

## Identity, causal and statistical obligations

The native signed-admission code authenticates evidence against a host-supplied
trust snapshot; it does not create that trust snapshot. The product owner must
load current keys, controller relationships, scopes, epochs and revocations from
an authority store that is independent of the submitted request. Cached verified
objects must be reverified after trust rotation or revocation.

Causal identification remains conditional on the frozen plan's assumptions:
consistency, support, correct propensity, appropriate cluster independence and
absence or bounded treatment of confounding. Unsupported assumptions produce
insufficient evidence; an outcome model cannot repair zero support.

Intervals and point estimates do not by themselves implement family-wide alpha
allocation, privacy review, change-point admission or future-window scheduling.
The independent decision requires their receipt digests, while the responsible
owners must provide the actual evidence.

## Product integration obligations

Repository source now provides the evaluator, signed evidence admission, durable
holdout journal and signed observed-time gate. A product receipt still has to
name and prove:

1. the scheduler and immutable evaluation-plan store;
2. the authorized durable final-holdout file namespace, single-writer domain,
   independently persisted signed anchor and monotonic freshness watermark;
3. the authenticated dataset, outcome-observer and candidate manifests;
4. the exact fold assignments and nuisance-model runtime;
5. the target host, resource measurements and incomplete/censored counts;
6. actual future calendar windows and independently identified snapshots;
7. retention, subgroup/privacy and unlearning evidence;
8. the distinct selector, operator and release principals.

A fixture using synthetic or virtual-clock future timestamps cannot satisfy the
future-calendar or longitudinal efficacy claim. Passing native tests proves the
admission logic, not the external event.

## Status truth hierarchy

Do not infer one lifecycle state by combining unrelated status words from several
files. For this module the authorities are deliberately separated:

- `NATIVE_MAPPING.md` describes source capabilities present in the checked-out
  candidate and the host obligations they leave open.
- `docs/modules/learning.eval/IMPLEMENTATION_MAP.json` is source-navigation and
  claim-boundary metadata. Its `sourceBase` is a frozen generation baseline,
  not an exact-HEAD execution receipt.
- `.github/workflows/hepta-lane-e-gap-closure.yml` produces retained exact-HEAD
  and pull-request synthetic-merge **source qualification** receipts only after
  closed-world verification, compilation, native/cross-crate/cross-language
  tests, strict lint and formatting succeed.
- `EVIDENCE_ADMISSION.md` defines the authenticated runtime evidence boundary.
  A source receipt does not become product execution, real future-calendar
  efficacy, independent acceptance, selection, promotion or release evidence.

This hierarchy is the tie-breaker if a planning label such as `planned` appears
beside a source label such as `existing_bound`: package lifecycle and source
presence are different dimensions.

## Qualification mapping

Focused tests live in:

- `src/lib_tests.rs`;
- `src/ope_tests.rs` and `src/ope_confidence_tests.rs`;
- `src/sequential_tests.rs`;
- `src/temporal_fold_tests.rs` and `src/temporal_evaluation_tests.rs`;
- `src/closure_tests.rs`;
- `src/durable_holdout_tests.rs`;
- `src/longitudinal_time_tests.rs`;
- inline tests in `src/authenticated_holdout.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`. The CI workflow retains
machine-readable receipts for the exact source head and, on pull requests, the
ordered-parent synthetic merge. Those artifacts explicitly carry source-only
nonclaims.
