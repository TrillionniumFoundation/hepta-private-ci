# `learning.operator` native implementation mapping

This file separates deterministic target construction, applicability admission,
sensor geometry, Bellman reference evaluation and world-model estimation. No
symbol in this crate is an online policy, artifact selector or production
writer.

## Compatibility and naming

The original public `train(TrainingRequest)` function is retained for source
compatibility, but it delegates to `build_targets`. Its actual behavior is a
bounded deterministic Bellman-target builder over caller-supplied continuation
values. It does not fit a neural network or prove a complete Bellman operator.

The complete regularity gate uses `OperatorRegularityAssessmentV1`; the legacy
`RegularityProfile` contains only target-builder diagnostics and must not be
interpreted as the Hölder/operator qualification profile.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| build deterministic Bellman targets | `build_targets` (`train` compatibility alias) | `src/lib.rs` | implemented |
| admit smooth-axis applicability | `validate_applicability_certificate` | `src/reference.rs` | implemented |
| build fixed sensor core | `build_sensor_core` | `src/reference.rs` | implemented |
| execute tabular Bellman reference | `evaluate_bellman_reference` | `src/reference.rs` | implemented |
| admit rank/gain/shape/OOD/error budget | `admit_operator_regularity` | `src/reference.rs` | implemented |
| fit action-conditioned tabular dynamics | `fit_transition_model` | `src/world_model.rs` | implemented |
| predict supported transition distribution | `predict_transition` | `src/world_model.rs` | implemented |

## Applicability and sensor core

`OperatorApplicabilityCertificateV1` binds the axis partition, domain, action
space, Hölder/Lipschitz profiles, ellipticity lower bound, control interval,
independent evaluator credential, fallback, expiry and decision. Non-positive
ellipticity, expired certificates and unsupported control intervals fail before
operator evaluation.

`build_sensor_core` uses deterministic farthest-point insertion over a bounded,
canonical candidate design. It rejects duplicate identities, duplicate
coordinates, mixed dimensions and coordinates outside normalized `[0,1]`.
The manifest records selected points, fill distance, separation radius, mesh
ratio and a hull digest. A zero separation radius or mesh ratio above the pilot
bound fails.

## Bellman reference and regularity

`evaluate_bellman_reference` requires the complete Cartesian product of the
registered sensor and action identities. Missing or duplicate cells fail. It
computes Q32 targets, deterministic greedy actions and action gaps; ties break by
canonical action ID. This reference is the oracle for any later learned model.

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

## World-model baseline

`fit_transition_model` builds a deterministic action-conditioned tabular model
from an immutable dataset. For every supported `(state, action)` it records the
mean bounded outcome and a branch distribution whose Q32 probabilities sum
exactly to one. `predict_transition` rejects unsupported pairs rather than
extrapolating and marks every prediction synthetic with deny-all authority.
Synthetic predictions cannot become independent factual outcomes.

## Host and external obligations

A production integration must still provide:

1. authenticated applicability and regularity evidence;
2. immutable dataset and artifact lineage;
3. actual model/training code, optimizer, precision, device and runtime tuple
   when a learned model is introduced;
4. target-host training and inference measurements;
5. held-out one-step and multistep calibration, change-point and OOD evidence;
6. independent future-time evaluation, retention and rollback;
7. a separate selector and process loader.

The simplest qualified implementation wins. A tabular or deterministic
reference satisfying the objective is preferred over an unnecessary neural
operator.

## Qualification mapping

Focused tests live in:

- `src/lib_tests.rs`;
- `src/reference_tests.rs`;
- `src/world_model_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.
