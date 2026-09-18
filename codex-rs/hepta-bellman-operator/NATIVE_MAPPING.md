# `learning.operator` native implementation mapping

This file separates deterministic target construction, applicability admission,
sensor geometry, Bellman reference evaluation, simplest-sufficient tabular
learning and world-model estimation. No symbol in this crate is an online
policy, artifact selector or production writer.

## Compatibility and naming

The original public `train(TrainingRequest)` function is deprecated and retained
only for source compatibility; it delegates to `build_targets`. Its actual
behavior is a bounded deterministic Bellman-target builder over caller-supplied
continuation values. New callers use `build_targets`; this alias does not fit a
neural network or prove a complete Bellman operator.

The complete regularity gate uses `OperatorRegularityAssessmentV1`; the legacy
`RegularityProfile` contains only target-builder diagnostics and must not be
interpreted as the Hölder/operator qualification profile.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| build deterministic Bellman targets | `build_targets` (`train` compatibility alias) | `src/lib.rs` | implemented |
| admit smooth-axis applicability | `validate_applicability_certificate` | `src/reference.rs` | implemented |
| build work-bounded fixed sensor core | `build_sensor_core` | `src/sensor_bounded.rs` | implemented |
| execute tabular Bellman reference | `evaluate_bellman_reference` | `src/reference.rs` | implemented |
| fit complete simplest-sufficient operator | `fit_tabular_operator` / `fit_tabular_operator_strict_v2` | `src/learned.rs`, `src/learned_strict.rs` | implemented |
| admit host-pinned tabular candidate | `LoadedTabularOperatorV1::from_pinned_payload` | `src/loaded.rs` | implemented |
| predict from admitted tabular candidate | `LoadedTabularOperatorV1::predict` | `src/loaded.rs` | implemented |
| admit rank/gain/shape/OOD/error budget | `admit_operator_regularity` | `src/reference.rs` | implemented |
| fit action-conditioned tabular dynamics | `fit_transition_model` | `src/world_model.rs` | implemented |
| bind complete world-model semantic payload | `world_model_payload_digest_v1` | `src/world_model.rs` | implemented |
| admit host-pinned world model | `LoadedTabularWorldModelV1::from_pinned_model` | `src/world_model.rs` | implemented |
| predict supported transition distribution | `LoadedTabularWorldModelV1::predict` | `src/world_model.rs` | implemented |
| admit frozen world-model qualification evidence | `admit_world_model_qualification` | `src/world_model_qualification.rs` | implemented |

## Applicability and sensor core

`OperatorApplicabilityCertificateV1` binds the axis partition, domain, action
space, Hölder/Lipschitz profiles, ellipticity lower bound, control interval,
independent evaluator credential, fallback, expiry and decision. Non-positive
ellipticity, expired certificates and unsupported control intervals fail before
operator evaluation.

`build_sensor_core` wraps the exact deterministic farthest-point reference with
an explicit conservative coordinate-work budget before any quadratic geometry
runs. The reference rejects duplicate identities, duplicate coordinates, mixed
dimensions and coordinates outside normalized `[0,1]`. The manifest records
selected points, fill distance, separation radius, mesh ratio and a hull digest.
A zero separation radius, mesh ratio above the pilot bound, or estimated exact
coordinate work above the source budget fails closed.

## Bellman reference, learned baseline and regularity

`evaluate_bellman_reference` requires the complete Cartesian product of the
registered sensor and action identities. Missing or duplicate cells fail. It
computes Q32 targets, deterministic greedy actions and action gaps; ties break by
canonical action ID. This reference is the oracle for any later learned model.

`fit_tabular_operator` is the first source-complete trainable operator profile.
It canonicalizes a frozen sensor-by-action grid, requires the same minimum of
two actions as the deterministic reference, validates every sample and requires
a configurable positive minimum sample count for every grid cell. The
base V1 fitter now rejects a duplicate `evidence_digest` globally even when a
caller relabels that evidence with a different `sample_id`; the strict V2
surface retains the same fail-closed rule as an additive admission layer. The
artifact stores each cell's mean, minimum, maximum, sample count and evidence
digest. Caller order cannot change the result.

Raw artifact prediction helpers are crate-internal qualification helpers rather
than composition APIs. External consumers must first admit a host-selected,
pinned payload with `LoadedTabularOperatorV1::from_pinned_payload` and then use
`LoadedTabularOperatorV1::predict`. Unknown sensor/action cells remain OOD, and
every prediction is learned, synthetic and `DENY_ALL`.

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
from an immutable dataset. It rejects both duplicate sample identities and
duplicate underlying `evidence_digest` values, so replayed evidence cannot alter
counts, means or transition frequencies merely by changing a sample ID. For
every supported `(state, action)` it records the mean bounded outcome and a
branch distribution whose Q32 probabilities sum exactly to one.

The public composition surface is pinned loading, not direct prediction from a
mutable public model. `world_model_payload_digest_v1` binds all
prediction-relevant semantic fields; `LoadedTabularWorldModelV1::from_pinned_model`
checks model, dataset, original model digest and the independent host payload
pin before retaining private immutable state.
`LoadedTabularWorldModelV1::predict` rejects unsupported pairs rather than
extrapolating and marks every prediction synthetic with deny-all authority.
Synthetic predictions cannot become independent factual outcomes.

`admit_world_model_qualification` consumes already frozen statistical evidence
under a digest-bound profile. It requires minimum effective/held-out support,
independent snapshots, future windows and bounded held-out MAE, temporal
calibration error, drift score and confidence half-width. The admission record
remains synthetic/qualification-only with `DENY_ALL`; this source gate does not
manufacture future-time, live-world or independent acceptance evidence.

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
- `src/loaded_tests.rs`;
- `src/world_model_tests.rs`;
- inline work-budget tests in `src/sensor_bounded.rs`;
- inline statistical-admission tests in `src/world_model_qualification.rs`.

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
The legacy raw/indexed prediction helpers remain available only inside this
crate for qualification tests; they are no longer re-exported from the crate
root. Product and cross-crate callers therefore use the independently pinned
loaded surface rather than a caller-supplied mutable artifact.

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


## Qualification-only operator acceptance

`codex-rs/hepta-operator-acceptance` is Cargo-bound to `learning.operator`
and is part of the module's qualification source envelope. It provides formal
environment checks, trusted-time/nonces, durable watermarks, frozen-evidence
rechecks, external trust-policy pins, signature verification and durable
acceptance receipts. Its declared scope remains
`qualification_evidence_only`, `automatic_transition=false`, and it grants no
Enforce, promotion, outbound or retirement authority. This ceremony is source
implementation for independent qualification evidence; it is not product
selection, canary, promotion or release.
