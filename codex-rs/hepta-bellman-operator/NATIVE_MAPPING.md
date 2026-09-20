# `learning.operator` native implementation mapping

This file separates deterministic target construction, applicability admission,
sensor geometry, Bellman reference evaluation, replay-safe simplest-sufficient
learning, pinned candidate loading, world-model estimation and statistical
qualification admission. No symbol in this crate is an online policy, artifact
selector or production writer.

## Compatibility and naming

The original public `train(TrainingRequest)` symbol remains only as a deprecated
source-compatibility alias for `build_targets`. Its actual behavior is bounded
deterministic Bellman-target construction over caller-supplied continuation
values. New callers must use `build_targets`; neither symbol fits a neural model
or proves a complete Bellman operator.

The complete regularity gate uses `OperatorRegularityAssessmentV1`; the legacy
`RegularityProfile` contains only target-builder diagnostics and must not be
interpreted as the Hölder/operator qualification profile.

## Public design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| build deterministic Bellman targets | `build_targets` | `src/lib.rs` | implemented |
| admit smooth-axis applicability | `validate_applicability_certificate` | `src/reference.rs` | implemented |
| build fixed sensor core under explicit exact-work budget | `build_sensor_core` | `src/sensor_bounded.rs` | implemented |
| execute tabular Bellman reference | `evaluate_bellman_reference` | `src/reference.rs` | implemented |
| fit replay-safe complete simplest-sufficient operator | `fit_tabular_operator` | `src/admitted.rs` | implemented |
| fit strict complete-grid operator | `fit_tabular_operator_strict_v2` | `src/learned_strict.rs` | implemented |
| load independently pinned tabular payload | `LoadedTabularOperatorV1::from_pinned_payload` | `src/loaded.rs` | implemented |
| predict from validated tabular payload | `LoadedTabularOperatorV1::predict` | `src/loaded.rs` | implemented |
| admit rank/gain/shape/OOD/error budget | `admit_operator_regularity` | `src/reference.rs` | implemented structural |
| authenticate frozen dataset + exact rows | `verify_operator_dataset_v1` / `fit_*_verified_v1` | `src/dataset_binding.rs` | implemented |
| authenticate independent evaluator | `admit_authenticated_applicability_v1` / `admit_authenticated_regularity_v1` | `src/authenticated_admission.rs` | implemented |
| fit replay-safe action-conditioned tabular dynamics | `fit_transition_model` | `src/admitted.rs` | implemented |
| load independently pinned world-model payload | `LoadedWorldModelV1::from_pinned_payload` | `src/world_model_loaded.rs` | implemented |
| predict from validated world-model payload | `LoadedWorldModelV1::predict` | `src/world_model_loaded.rs` | implemented |
| admit frozen world-model statistical evidence | `admit_world_model_qualification` | `src/world_model_qualification.rs` | implemented |

`learned.rs::predict_tabular_operator`,
`learned_strict.rs::predict_tabular_operator_indexed_v2` and
`world_model.rs::predict_transition` remain crate-internal implementation/test
helpers. They are deliberately not exported from `lib.rs`; cross-crate callers
cannot bypass pinned loading by passing a mutable public artifact directly.

## Replay admission and action-domain contract

Evidence identity is the replay boundary. Public fitting rejects a repeated
`evidence_digest` even when a caller supplies a different `sample_id`.
`build_targets` applies the same rule to `support_digest`, so relabelling one
observation cannot raise target-builder counts. The world-model wrapper rejects
duplicate evidence before transition frequencies or mean outcomes are computed.

The public tabular fitting path also requires at least two registered actions,
matching the deterministic Bellman-reference action-domain floor. This removes
the former state in which a fitted artifact could be valid to one path but
structurally ineligible for the reference path.

## Applicability and bounded sensor core

`OperatorApplicabilityCertificateV1` binds the axis partition, domain, action
space, Hölder/Lipschitz profiles, ellipticity lower bound, control interval,
independent evaluator credential, fallback, expiry and decision. Non-positive
ellipticity, expired certificates and unsupported control intervals fail before
operator evaluation.

The exact reference sensor algorithm still uses canonical farthest-point
insertion, pairwise duplicate-coordinate checks and exact selected-point
geometry. `sensor_bounded::build_sensor_core` now computes a conservative
coordinate-work estimate before entering that algorithm. The estimate covers
all-pairs candidate comparison, candidate-to-selected distance updates and
selected-pair separation work. Work above the source budget fails closed before
the quadratic/exact loop starts. This is a source work ceiling, not a target-host
latency measurement; a selected host may impose a lower reviewed profile.

The core rejects duplicate identities, duplicate coordinates, mixed dimensions
and coordinates outside normalized `[0,1]`. The manifest records selected
points, fill distance, separation radius, mesh ratio and a hull digest. A zero
separation radius or mesh ratio above the pilot bound fails.

## Bellman reference, learned baseline and regularity

`evaluate_bellman_reference` requires the complete Cartesian product of the
registered sensor and action identities. Missing or duplicate cells fail. It
computes Q32 targets, deterministic greedy actions and action gaps; ties break by
canonical action ID. This reference is the oracle for later learned candidates.

`fit_tabular_operator` is the public simplest-sufficient fitting path. It first
applies replay and action-domain admission and then canonicalizes a frozen
sensor-by-action grid. Every cell needs a positive configurable sample floor.
The artifact stores mean, minimum, maximum, sample count and bound evidence
digest. Caller order cannot change the result.

A candidate is not a runtime object. `encode_tabular_payload_v1` creates bounded
candidate bytes, while `LoadedTabularOperatorV1::from_pinned_payload` requires an
independently selected payload pin and validates payload, artifact, objective,
dataset, sensor, training profile, generation, canonical grid, statistics and
deny-all authority once. Repeated `predict` calls use private immutable loaded
state and reject unsupported cells. Predictions remain learned, synthetic and
`DENY_ALL`.

This profile deliberately implements the simplest sufficient learner. A neural
or low-rank tensor candidate is not required merely because the architecture
permits one. Such a candidate needs a new immutable training/runtime profile and
must independently justify itself against deterministic and tabular baselines.

`admit_operator_regularity` intersects:

- measured rank `1..64`;
- reconstruction gain at most `1.02`;
- zero required monotonicity and positivity violations;
- bounded Hölder and action-Lipschitz residuals;
- OOD false acceptance below `0.5%`;
- explicit non-negative error components with total normalized error at most
  `0.05`;
- independent approval when one component consumes more than half of the total.

Unmeasured components are not silently omitted. A learned implementation must
publish every required component under a separately reviewed model/runtime
profile.

## World-model baseline and pinned loading

`fit_transition_model` applies replay-safe admission before the deterministic
action-conditioned tabular estimator. For every supported `(state, action)` it
records the mean bounded outcome and a branch distribution whose Q32
probabilities sum exactly to one. The internal raw predictor still rejects
unsupported pairs and marks predictions synthetic with deny-all authority, but
it is not a public cross-crate API.

`encode_world_model_payload_v1` emits bounded candidate bytes.
`LoadedWorldModelV1::from_pinned_payload` checks an independent payload digest
plus model, dataset and model-identity pins, validates canonical estimate and
branch ordering, count/probability consistency, bounded values, deny-all
authority and the model digest, and only then creates private immutable loaded
state. `LoadedWorldModelV1::predict` is the public prediction surface.
Synthetic predictions cannot become independent factual outcomes.

## World-model qualification evidence

`admit_world_model_qualification` does not calculate or invent scientific
evidence. It consumes externally produced frozen measurements under a
digest-bound profile and fails closed unless all declared floors and bounds are
met. The source admission currently requires at least:

- effective sample size `200`;
- held-out sample count `200`;
- three independently identified snapshots;
- two future windows;
- bounded held-out error, temporal calibration error, drift score and confidence
  half-width under the supplied profile;
- bound evaluator credential and evidence digests.

A successful result remains `DENY_ALL`. It is only an input to later independent
qualification; it is not operator acceptance, activation, canary, promotion or
release. Real future windows, target-device measurements and live-world outcome
evidence cannot be self-issued by this crate.

## Qualification acceptance package

`docs/modules/CARGO_BINDINGS.json` also binds
`codex-rs/hepta-operator-acceptance` to `learning.operator`. That package uses
trusted time, nonce claims, durable watermarks, frozen-evidence revalidation,
externally pinned trust policy and signed receipts. Its scope is explicitly
`qualification_evidence_only`, `automatic_transition` is false, and its signed
declaration grants no Enforce, promotion, outbound or retirement authority.
It must not be described as production acceptance.

## Host and external obligations

A production integration still has to provide, outside this source library:

1. authenticated applicability and regularity evidence;
2. immutable dataset and artifact lineage;
3. selected training/runtime profile, precision, device and runtime tuple;
4. target-host training and inference measurements;
5. real held-out one-step and multistep calibration plus change-point/OOD data;
6. independent future-time evaluation, retention, unlearning and rollback;
7. an authenticated product caller, separate selector and selected-process loader;
8. independent operator acceptance beyond qualification-evidence sealing;
9. canary, promotion and release decisions.

The simplest qualified implementation wins. A tabular or deterministic
reference satisfying the objective is preferred over an unnecessary neural
operator.

## Qualification mapping

Focused source tests include:

- `src/lib_tests.rs` — target construction and replay admission;
- `src/admitted.rs` — evidence replay and action-domain admission;
- `src/reference_tests.rs` — applicability, exact sensor/reference and regularity;
- `src/sensor_bounded.rs` — exact-work budgeting;
- `src/learned_tests.rs` — deterministic complete-grid fitting;
- `src/loaded_tests.rs` — pinned tabular payload validation and process reload;
- `src/world_model_tests.rs` — deterministic action-conditioned baseline;
- `src/world_model_loaded.rs` — pinned world-model load/tamper rejection;
- `src/world_model_qualification.rs` — support/future/drift/confidence admission.

Cross-crate linkage and owner-store reload/rollback are exercised in
`hepta-shadow-qualification/tests/lane_e_api_contract.rs` and
`hepta-shadow-qualification/tests/support/tabular_reload.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.

These are source and engineering qualification tests. They are not a substitute
for real future-calendar efficacy, selected-host resource measurements,
independent acceptance or production release evidence.


## Authenticated dataset and evaluator boundary

Cross-owner qualification should not trust a detached `dataset_digest` or a
nonzero evaluator credential digest. `verify_operator_dataset_v1` validates the
self-describing `DatasetSnapshotReceiptV3`, authenticates that exact dataset
identity with the host-owned `LearningEvidenceVerifierV1`, and privately
constructs `VerifiedOperatorDatasetV1`. The verified fitters additionally
require the training samples' evidence-digest set to equal the frozen source
record set.

`admit_authenticated_applicability_v1` and
`admit_authenticated_regularity_v1` first run the deterministic structural
checks, then require an authenticated Evaluator signature over the exact
structural digest. Generator/evaluator principal, credential chain, signing key
and controller separation is enforced by the existing learning-ledger trust
model. The regularity signature therefore also binds
`dominant_component_approved`; it is no longer sufficient as a naked caller
boolean on the authenticated path.

## Explicit read consumer

Agentd's `PinnedCognitiveRanker` is a real, explicitly attached consumer of
`LoadedTabularOperatorV1`. It binds the selected learning-artifact manifest,
revalidates the current registry/revocation view on each cognitive read and only
reorders already-admitted records. This proves a narrow read consumer, not an
automatic training/evaluation/selection/new-process loop, production activation
or longitudinal task benefit.
