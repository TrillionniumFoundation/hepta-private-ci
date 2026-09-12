# learning.operator: implementation design

Parent: `docs/modules/learning.operator/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: deterministic reference, simplest-sufficient tabular learner and action-conditioned world-model source candidate implemented; current exact-head and synthetic-merge CI determine source qualification, while real-model efficacy and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-bellman-operator`.
Packages: `HBO-0-BELLMAN-OPERATOR-CONTRACTS`, `HBO-1-OPERATOR-SENSOR-CORE`, `HBO-2-BELLMAN-OPERATOR-SHADOW`, `BIO-3-WORLD-MODEL-PREDICTION-ERROR`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Existing compatible APIs remain available; no operation creates another authority or execution spine.

## 2. Public operations and contract details

`build_sensor_core(design) -> OperatorSensorCoreManifestV1`; `fit_transition_model(dataset) -> TabularWorldModelV1`; `build_targets(dataset, objective) -> BellmanOperatorArtifact`; `fit_tabular_operator(dataset, sensor_core, profile) -> TabularOperatorArtifactV1`; `predict_transition(model, state, legal_action) -> WorldModelPredictionV1`; `predict_tabular_operator(artifact, sensor, legal_action) -> TabularOperatorPredictionV1`; `admit_operator_regularity(assessment) -> OperatorRegularityAdmissionV1`.

The original `train` function remains a compatibility alias for `build_targets`; it is explicitly a target builder, not a neural trainer. Transition/dynamics estimation and continuation-value estimation have separate artifacts and evidence.

## 3. State records and transaction design

There is no production source writer. Training reads immutable ledger-bound datasets and emits deny-all candidate values for `learning.artifacts`. Sensor cores are fixed versioned designs, not replay caches. Artifacts bind axis partition, conditioning snapshot, model and dataset lineage, normalized units, code/runtime/device, error budget, applicability certificate and predecessor through the artifact owner.

The tabular learner requires a complete canonical sensor-by-action grid and a minimum sample count for every cell. It stores per-cell mean, minimum, maximum, sample count and evidence digest. Missing or underfilled cells fail. Predictions outside the fitted grid fail rather than extrapolate.

## 4. Deterministic algorithm and scheduling

Partition smooth, jump and hard axes; reject unsupported ellipticity or regularity rather than inject noise into hard state; construct deterministic farthest-point sensors; measure fill distance, separation radius and mesh ratio; run the complete tabular Bellman reference; fit the simplest sufficient tabular candidate; and measure rank, reconstruction, shape, OOD and complete error budget separately.

The action-conditioned world-model baseline groups immutable observed samples by state/action, publishes exact Q32 branch distributions that sum to one and rejects unsupported pairs. Every prediction is marked synthetic. A model prediction cannot become an independent factual outcome.

A later neural or low-rank tensor model must use a separately reviewed training profile and must beat or justify itself against the deterministic/tabular reference. Source presence alone cannot bypass applicability, future calibration, retention or rollback gates.

## 5. Capacity and performance profile

Canonical smooth dimensions are at most 32, sensor count at most 4096, action count at most 128, measured rank at most 64, reconstruction gain at most 1.02 and total normalized error at most 0.05. The tabular grid is bounded to 262144 cells and its training rows to 1000000. The world-model baseline is separately bounded by its state/action and branch limits. Training compute, memory and simulator calls remain profile budgets.

These are source bounds, not target-host measurements. A coordinate failing assumptions uses a qualified simpler fallback, not a fabricated certificate.

## 6. Concrete verification cases

- OP-01: analytic sensor/Bellman table reproduces canonical Q32 goldens.
- OP-02: degenerate diffusion, bad mesh ratio or excessive reconstruction gain disables the learned path.
- OP-03: a high in-sample fit with poor future calibration/retention fails evaluation.
- OP-04: model-generated rollouts remain synthetic and cannot become independent factual outcome evidence.

Every case is mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`. Additional learned-grid tests verify order independence, complete-cell admission, minimum samples and domain-bounded prediction.

## 7. Integration, rollback and capability ceiling

NDU consumes bounded continuation values but does not replace the world model. C1 may use the simpler baseline allowed by its registered package; it must not silently bypass existing DAG predecessors. Rollback loads a complete compatible operator/sensor tuple under current revocations.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `build_targets` in [codex-rs/hepta-bellman-operator/src/lib.rs](../../../codex-rs/hepta-bellman-operator/src/lib.rs); `fit_tabular_operator` in [codex-rs/hepta-bellman-operator/src/learned.rs](../../../codex-rs/hepta-bellman-operator/src/learned.rs); `fit_transition_model` in [codex-rs/hepta-bellman-operator/src/world_model.rs](../../../codex-rs/hepta-bellman-operator/src/world_model.rs). Deterministic targets, tabular operator fitting and action-conditioned world-model baseline implemented.
- **State and recovery:** Pure candidate artifacts bind immutable data/profile/sensor identities. encode_tabular_payload_v1 and LoadedTabularOperatorV1 add bounded persisted candidate encoding and independently pinned, once-validated prediction. Storage and selection remain with learning.artifacts and its host. train is a compatibility alias for target construction; the separate tabular learner requires a complete supported sensor/action grid and retains per-cell sample statistics.
- **Source tests:** [codex-rs/hepta-bellman-operator/src/learned_tests.rs](../../../codex-rs/hepta-bellman-operator/src/learned_tests.rs), [codex-rs/hepta-bellman-operator/src/world_model_tests.rs](../../../codex-rs/hepta-bellman-operator/src/world_model_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md](../../../codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md), [docs/learning/HOLDER_BELLMAN_SPEC.md](../../../docs/learning/HOLDER_BELLMAN_SPEC.md).
- **Remaining work:** A neural/tensor model, device execution, independent mathematical applicability and future calibration/retention require separate evidence; model predictions remain synthetic observations.

## 9. Native closure and remaining evidence

Repository-controlled source coverage includes applicability admission, fixed sensor geometry, deterministic Bellman reference, simplest-sufficient tabular fitting, regularity/error-budget admission, action-conditioned dynamics and OOD rejection. `../../../scripts/hepta-lane-e-closure.py` verifies symbol and test mappings, while `.github/workflows/hepta-lane-e-gap-closure.yml` supplies exact-head and synthetic-merge compilation, tests, strict lint and formatting gates.

The repository cannot self-issue independent mathematical review, real neural/model-runtime identity, target device measurements, future-time calibration/retention, live-world transition evidence, operator acceptance, selected new-process loading, canary, promotion or release. Those capability gates remain open until external owners provide exact-candidate receipts.
