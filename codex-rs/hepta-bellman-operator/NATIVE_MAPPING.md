# `learning.operator` native implementation mapping

This file separates deterministic target construction, applicability admission,
sensor geometry, Bellman reference evaluation, simplest-sufficient tabular
learning and world-model estimation. No symbol in this crate is an online
policy, artifact selector or production writer.

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
| fit complete simplest-sufficient operator | `fit_tabular_operator` | `src/learned.rs` | implemented |
| predict only a fitted sensor/action cell | `predict_tabular_operator` | `src/learned.rs` | implemented |
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

## Bellman reference, learned baseline and regularity

`evaluate_bellman_reference` requires the complete Cartesian product of the
registered sensor and action identities. Missing or duplicate cells fail. It
computes Q32 targets, deterministic greedy actions and action gaps; ties break by
canonical action ID. This reference is the oracle for any later learned model.

`fit_tabular_operator` is the first source-complete trainable operator profile.
It canonicalizes a frozen sensor-by-action grid, validates every sample,
rejects a repeated evidence digest even when a caller relabels the sample ID,
and requires a configurable positive minimum sample count for every grid cell.
The artifact stores each cell's mean, minimum, maximum, sample count and
evidence digest. Caller order cannot change the result. The raw
`predict_tabular_operator` compatibility surface now revalidates retained
structure on every call and is deprecated for new integration; independently
pinned inference uses `LoadedTabularOperatorV1`. Unknown cells remain OOD and
all outputs remain learned/synthetic with `DENY_ALL` authority.

This profile deliberately implements the simplest sufficient learner. A neural
or low-rank tensor candidate is not required merely because the architecture
permits one. Such a candidate needs a new immutable training/runtime profile and
must independently justify itself against the deterministic and tabular
baselines.

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
from an immutable dataset and rejects duplicate underlying evidence globally,
including replays under a different sample ID. For every supported
`(state, action)` it records the mean bounded outcome and a branch distribution
whose Q32 probabilities sum exactly to one. The raw `predict_transition`
compatibility surface is deprecated for new integration. Persisted inference
uses `encode_world_model_payload_v1` plus
`LoadedTabularWorldModelV1::from_pinned_payload`, whose host pin binds the full
payload, model ID, model digest and dataset digest before private immutable
prediction. Unsupported pairs abstain and every prediction remains synthetic
with deny-all authority. Synthetic predictions cannot become independent
factual outcomes.

## Host and external obligations

A production integration must still provide:

1. authenticated applicability and regularity evidence;
2. immutable dataset and artifact lineage;
3. actual training code, profile, precision, device and runtime tuple;
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
- `src/learned_tests.rs`;
- `src/world_model_tests.rs`;
- `src/loaded_tests.rs`;
- `src/loaded_world_model_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.


## Persisted tabular candidate loading

`encode_tabular_payload_v1` emits a bounded owner-local `HEPTTB01` payload for the
existing `learning.artifacts` create-only storage APIs. It does not open another
store. The format contains model identity, generation, five digests and canonical
sensor/action cells with sample counts, Q32 means/minima/maxima and evidence.
All integers are big-endian; counts are bounded before allocation. The payload
ceiling is 64 MiB, the grid is at most 262,144 cells and the existing sensor,
action and sample bounds apply. Unknown versions, trailing/truncated bytes,
noncanonical or incomplete grids and invalid statistics reject.

A host-selected `TabularPayloadPinV1` binds payload, original training-artifact,
objective, dataset, sensor, training-profile and generation identities.
`LoadedTabularOperatorV1::from_pinned_payload` checks that independent pin and
validates once; its private immutable state permits O(log n) repeated prediction.
The original indexed V2 function validates the public mutable artifact in O(n)
on every call, before its binary search. These are different cost profiles.

The original training digest includes samples not retained in these sufficient
statistics; it is retained rather than falsely reconstructed. The artifact owner
must first establish current selection, compatible manifests and non-revoked
lineage. A hash computed from received bytes is not independent admission.
`src/loaded_tests.rs` fits actual tabular targets and observes baseline, changed
candidate and the same predecessor payload in three separate processes. That is
an engineering reload/rollback test, not a production learning or future-gain
claim. Scientific evaluation and actual host wiring remain separate gates.

The existing `hepta-shadow-qualification` durable-learning integration target now
also composes the strict tabular learner with the existing `learning.artifacts`
create-only payload/snapshot APIs and `load_pinned_candidate`, then the private
loaded predictor. `tests/support/tabular_reload.rs` checks separate-process
baseline/candidate/original-predecessor predictions and refuses both a revoked
predecessor and its descendant under the current registry witness. The parent
holds expected payload/manifest/registry pins outside the files being inspected;
no extra artifact store or production selection is introduced. This is executable
cross-owner engineering qualification, not an authenticated external operator
acceptance, future-window efficacy result or live C1 deployment.


## Persisted world-model candidate loading

`encode_world_model_payload_v1` emits the complete retained transition
prediction surface under the bounded `HEPTWM01` format. A host-selected
`WorldModelPayloadPinV1` binds the payload digest, model identity, model digest
and dataset digest. `LoadedTabularWorldModelV1::from_pinned_payload` verifies
that independent pin, canonical state/action ordering, sample-count totals,
branch-count totals, exact Q32 probabilities, bounded outcomes and deny-all
authority once before exposing O(log n) repeated lookup. Because V1 transition
estimates do not retain the original per-sample evidence set, a raw public
`TabularWorldModelV1` cannot independently reconstruct its historical
estimate digests; therefore raw prediction remains compatibility-only and the
pinned payload is the authenticated load boundary.
