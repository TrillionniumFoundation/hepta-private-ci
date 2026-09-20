# learning.operator: implementation design

Parent: `docs/modules/learning.operator/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: deterministic reference, replay-safe simplest-sufficient tabular learner, pinned candidate loaders, action-conditioned world-model baseline and frozen statistical-evidence admission are source implemented; current exact-head and synthetic-merge CI determine repository qualification, while live efficacy, target-host measurements, independent acceptance and release remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Exclusive root: `codex-rs/hepta-bellman-operator`.
Cargo-bound qualification package: `codex-rs/hepta-operator-acceptance`.
Packages: `HBO-0-BELLMAN-OPERATOR-CONTRACTS`, `HBO-1-OPERATOR-SENSOR-CORE`, `HBO-2-BELLMAN-OPERATOR-SHADOW`, `BIO-3-WORLD-MODEL-PREDICTION-ERROR`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md`, `../../../docs/modules/learning.operator/IMPLEMENTATION_MAP.json` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. No operation creates another authority or execution spine. The operator-acceptance package seals qualification evidence only; it is not production acceptance.

## 2. Public operations and contract details

Public target/reference and fitting surfaces are `build_targets`, `validate_applicability_certificate`, `build_sensor_core`, `evaluate_bellman_reference`, `admit_operator_regularity`, replay-safe `fit_tabular_operator`, strict `fit_tabular_operator_strict_v2` and replay-safe `fit_transition_model`.

Candidate values are not runtime objects. Cross-crate tabular inference requires `LoadedTabularOperatorV1::from_pinned_payload` followed by `LoadedTabularOperatorV1::predict`. Cross-crate world-model inference requires `LoadedWorldModelV1::from_pinned_payload` followed by `LoadedWorldModelV1::predict`. `admit_world_model_qualification` consumes externally produced frozen holdout/future/drift/confidence measurements and emits only deny-all qualification admission.

The raw artifact predictors remain crate-internal helpers and are not exported from `lib.rs`. A caller therefore cannot bypass independent payload pins by handing a mutable artifact directly to the public prediction API.

The original `train` function is deprecated and remains only as a compatibility alias for `build_targets`; it is explicitly target construction, not neural or tensor training. Transition/dynamics estimation and continuation-value estimation have separate artifacts and evidence.

## 3. State records and transaction design

There is no production source writer. Training reads immutable ledger-bound datasets and emits deny-all candidate values for `learning.artifacts`. Sensor cores are fixed versioned designs, not replay caches. Artifacts bind axis partition, conditioning snapshot, model and dataset lineage, normalized units, code/runtime/device profile, error budget, applicability certificate and predecessor through the artifact owner.

Evidence identity is the replay boundary. `build_targets` rejects repeated support digests even under different sample identities. Public tabular and world-model fitting reject repeated evidence digests before counts, means or transition probabilities are computed. The public tabular fit requires at least two registered actions, matching the deterministic reference contract.

The tabular learner requires a complete canonical sensor-by-action grid and a minimum sample count for every cell. Pinned loading validates payload, artifact/objective/dataset/sensor/training-profile/generation identities and immutable grid statistics once before prediction. Unsupported cells fail rather than extrapolate.

The world-model payload loader independently binds payload, model, dataset and model identity, then validates canonical estimates, canonical branches, count/probability consistency and deny-all authority before prediction. Unsupported state/action pairs fail.

## 4. Deterministic algorithm and scheduling

Partition smooth, jump and hard axes; reject unsupported ellipticity or regularity rather than inject noise into hard state; construct deterministic farthest-point sensors; measure fill distance, separation radius and mesh ratio; run the complete tabular Bellman reference; fit the simplest sufficient tabular candidate; and measure rank, reconstruction, shape, OOD and complete error budget separately.

The exact sensor implementation has quadratic/exact geometry components. The public `build_sensor_core` wrapper computes a conservative coordinate-work estimate covering candidate-pair comparison, farthest-point rounds and selected-pair separation. It fails before entering the exact algorithm if the source work budget is exceeded. This is not a target-host latency measurement.

The action-conditioned world-model baseline groups admitted immutable observed samples by state/action, publishes exact Q32 branch distributions that sum to one and rejects unsupported pairs. Every prediction is marked synthetic. A model prediction cannot become an independent factual outcome.

A later neural or low-rank tensor model is optional rather than implied by architecture. If introduced, it must use a separately reviewed immutable training/runtime profile and independently justify itself against deterministic and tabular baselines. Source presence alone cannot bypass applicability, future calibration, retention or rollback gates.

## 5. Capacity and performance profile

Canonical smooth dimensions are at most 32, sensor count at most 4096, action count at most 128, measured rank at most 64, reconstruction gain at most 1.02 and total normalized error at most 0.05. The tabular grid is bounded to 262144 cells and its training rows to 1000000. The world-model baseline is separately bounded by its state/action and branch limits. Exact sensor geometry additionally passes the explicit source coordinate-work budget before execution.

These are source bounds, not target-host measurements. A selected host may impose a lower profile. A coordinate failing assumptions uses a qualified simpler fallback, not a fabricated certificate.

## 6. Concrete verification cases

- OP-01: analytic sensor/Bellman tables reproduce canonical Q32 goldens and nominal maximum sensor geometry fails before excessive exact work.
- OP-02: degenerate diffusion, action-domain mismatch, replay contamination, payload drift or excessive regularity/error breach disables the learned path.
- OP-03: a high in-sample fit without effective support, future windows, retention and independent evaluation evidence is ineligible.
- OP-04: relabelled evidence cannot inflate world-model statistics; model-generated rollouts remain synthetic; public prediction requires an independently pinned loaded payload.

Every case is mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`. Cross-crate linkage and selected-file reload/rollback are tested separately from scientific efficacy.

## 7. Integration, rollback and capability ceiling

NDU consumes bounded continuation values but does not replace the world model. C1 may use the simpler baseline allowed by its registered package; it must not silently bypass existing DAG predecessors. Rollback loads a complete compatible operator/sensor tuple under current revocations through the artifact owner.

`hepta-operator-acceptance` adds formal-environment checks, trusted time, nonce claim, durable time watermark, frozen-evidence revalidation, externally pinned trust policy and signed receipt verification. Its scope is `qualification_evidence_only`, its challenge sets `automatic_transition=false`, and its declaration grants no Enforce, promotion, outbound or retirement authority.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `build_targets` in [codex-rs/hepta-bellman-operator/src/lib.rs](../../../codex-rs/hepta-bellman-operator/src/lib.rs); `fit_tabular_operator` in [codex-rs/hepta-bellman-operator/src/admitted.rs](../../../codex-rs/hepta-bellman-operator/src/admitted.rs); `fit_tabular_operator_strict_v2` in [codex-rs/hepta-bellman-operator/src/learned_strict.rs](../../../codex-rs/hepta-bellman-operator/src/learned_strict.rs); `LoadedTabularOperatorV1::from_pinned_payload` in [codex-rs/hepta-bellman-operator/src/loaded.rs](../../../codex-rs/hepta-bellman-operator/src/loaded.rs); `LoadedTabularOperatorV1::predict` in [codex-rs/hepta-bellman-operator/src/loaded.rs](../../../codex-rs/hepta-bellman-operator/src/loaded.rs); `validate_applicability_certificate` in [codex-rs/hepta-bellman-operator/src/reference.rs](../../../codex-rs/hepta-bellman-operator/src/reference.rs); `build_sensor_core` in [codex-rs/hepta-bellman-operator/src/sensor_bounded.rs](../../../codex-rs/hepta-bellman-operator/src/sensor_bounded.rs); `evaluate_bellman_reference` in [codex-rs/hepta-bellman-operator/src/reference.rs](../../../codex-rs/hepta-bellman-operator/src/reference.rs); `admit_operator_regularity` in [codex-rs/hepta-bellman-operator/src/reference.rs](../../../codex-rs/hepta-bellman-operator/src/reference.rs); `fit_transition_model` in [codex-rs/hepta-bellman-operator/src/admitted.rs](../../../codex-rs/hepta-bellman-operator/src/admitted.rs); `LoadedWorldModelV1::from_pinned_payload` in [codex-rs/hepta-bellman-operator/src/world_model_loaded.rs](../../../codex-rs/hepta-bellman-operator/src/world_model_loaded.rs); `LoadedWorldModelV1::predict` in [codex-rs/hepta-bellman-operator/src/world_model_loaded.rs](../../../codex-rs/hepta-bellman-operator/src/world_model_loaded.rs); `admit_world_model_qualification` in [codex-rs/hepta-bellman-operator/src/world_model_qualification.rs](../../../codex-rs/hepta-bellman-operator/src/world_model_qualification.rs); `prepare` in [codex-rs/hepta-operator-acceptance/src/lib.rs](../../../codex-rs/hepta-operator-acceptance/src/lib.rs); `verify_and_seal` in [codex-rs/hepta-operator-acceptance/src/lib.rs](../../../codex-rs/hepta-operator-acceptance/src/lib.rs); `verify_receipt` in [codex-rs/hepta-operator-acceptance/src/lib.rs](../../../codex-rs/hepta-operator-acceptance/src/lib.rs).
- **State and recovery:** Candidate encoding and loaded prediction are immutable. Storage, current selection and revocation remain with `learning.artifacts` and its host. Tabular and world-model loaded objects require independent pins; no public raw-artifact predictor is exported. `train` is deprecated target-construction compatibility only.
- **Statistical admission:** `admit_world_model_qualification` binds model/dataset/profile/evaluator/evidence digests and enforces declared holdout, effective-support, snapshot, future-window, calibration, drift and confidence bounds. It consumes measurements; it does not generate or self-certify them.
- **Source tests:** [codex-rs/hepta-bellman-operator/src/lib_tests.rs](../../../codex-rs/hepta-bellman-operator/src/lib_tests.rs), [codex-rs/hepta-bellman-operator/src/admitted.rs](../../../codex-rs/hepta-bellman-operator/src/admitted.rs), [codex-rs/hepta-bellman-operator/src/reference_tests.rs](../../../codex-rs/hepta-bellman-operator/src/reference_tests.rs), [codex-rs/hepta-bellman-operator/src/sensor_bounded.rs](../../../codex-rs/hepta-bellman-operator/src/sensor_bounded.rs), [codex-rs/hepta-bellman-operator/src/learned_tests.rs](../../../codex-rs/hepta-bellman-operator/src/learned_tests.rs), [codex-rs/hepta-bellman-operator/src/loaded_tests.rs](../../../codex-rs/hepta-bellman-operator/src/loaded_tests.rs), [codex-rs/hepta-bellman-operator/src/world_model_tests.rs](../../../codex-rs/hepta-bellman-operator/src/world_model_tests.rs), [codex-rs/hepta-bellman-operator/src/world_model_loaded.rs](../../../codex-rs/hepta-bellman-operator/src/world_model_loaded.rs), [codex-rs/hepta-bellman-operator/src/world_model_qualification.rs](../../../codex-rs/hepta-bellman-operator/src/world_model_qualification.rs).
- **Implementation and operating references:** [codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md](../../../codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md), [docs/learning/HOLDER_BELLMAN_SPEC.md](../../../docs/learning/HOLDER_BELLMAN_SPEC.md), [docs/modules/learning.operator/IMPLEMENTATION_MAP.json](../../../docs/modules/learning.operator/IMPLEMENTATION_MAP.json).
- **Remaining external work:** selected target-host execution, independent mathematical review, real future calibration/retention/live-world validation, production composition, independent operator acceptance beyond qualification-evidence sealing, canary, promotion and release. A neural/tensor model is required only if the simplest sufficient candidate fails the objective or a separately reviewed profile selects it.

## 9. Native closure and remaining evidence

Repository-controlled source coverage includes source-snapshot freshness verification, replay-safe target/fitting admission, consistent action-domain floor, bounded exact sensor geometry, deterministic Bellman reference, simplest-sufficient tabular fitting, pinned tabular/world-model loading, regularity/error-budget admission, action-conditioned dynamics, statistical qualification admission and OOD rejection. `../../../scripts/hepta-lane-e-closure.py` verifies the Lane-E symbol/test closed world, while `.github/workflows/hepta-lane-e-gap-closure.yml` supplies exact-head and synthetic-merge compilation, tests, strict lint and formatting gates.

The repository cannot self-issue independent mathematical review, selected target-device measurements, real future-time calibration/retention, live-world transition evidence, production product composition, independent operator acceptance, canary, promotion or release. Those capability gates remain open until external owners provide exact-candidate receipts.
