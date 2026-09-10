# learning.operator: implementation design

Parent: `docs/modules/learning.operator/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: deterministic reference, simplest-sufficient tabular learner and action-conditioned world-model source candidate implemented; exact-head and ordered-base synthetic-merge CI determine source qualification. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md` and `../../../docs/engineering/MODULE_ENGINEERING_STANDARD.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-bellman-operator`.
Packages: `HBO-0-BELLMAN-OPERATOR-CONTRACTS`, `HBO-1-OPERATOR-SENSOR-CORE`, `HBO-2-BELLMAN-OPERATOR-SHADOW`, `BIO-3-WORLD-MODEL-PREDICTION-ERROR`.

Concrete mappings are recorded in `../../../codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. No operation is an online policy, selector or production writer.

## 2. Public operations and contract details

The closed-world native surface includes:

- `build_targets` and its legacy `train` alias;
- `validate_applicability_certificate`;
- `build_sensor_core`;
- `evaluate_bellman_reference`;
- `admit_operator_regularity`;
- `fit_transition_model` and `predict_transition`;
- `fit_tabular_operator` and `predict_tabular_operator`;
- `fit_tabular_operator_strict_v2` and `predict_tabular_operator_indexed_v2`.

The original `train` function remains a deterministic Bellman-target builder, not a neural trainer. The strict V2 wrapper rejects duplicate underlying evidence even when callers relabel sample IDs. Indexed prediction validates canonical cell order and uses binary search instead of a linear full-grid scan.

## 3. State records and transaction design

There is no production source writer. Training reads an immutable, ledger-bound dataset and emits deny-all candidate values for `learning.artifacts`. Sensor cores are fixed versioned designs rather than replay caches. Artifacts bind objective, dataset, sensor core, model/training profile, runtime/device identity, error budget, applicability evidence and predecessor lineage through the artifact owner.

The tabular learner requires a complete canonical sensor-by-action grid and a positive minimum sample count for every cell. It stores mean, minimum, maximum, sample count and an evidence digest. Missing or underfilled cells fail. The strict path additionally requires globally unique source evidence digests so one observation cannot be counted twice under different sample IDs.

## 4. Deterministic algorithm and scheduling

Partition smooth, jump and hard axes; reject unsupported ellipticity or regularity; construct deterministic farthest-point sensors; measure fill distance, separation radius and mesh ratio; run the complete tabular Bellman reference; fit the simplest sufficient candidate; then measure rank, reconstruction, shape, OOD and each error-budget component separately.

The action-conditioned world-model baseline groups independently observed samples by state/action, publishes exact Q32 branch probabilities that sum to one and rejects unsupported pairs. Every model and operator prediction is synthetic and cannot become the independent factual outcome used to judge the same candidate.

A neural or low-rank tensor model requires a separately reviewed immutable profile and must justify itself against both deterministic and strict-tabular baselines.

## 5. Capacity and performance profile

Canonical bounds are: 32 smooth dimensions, 4,096 sensors, 128 actions, 262,144 tabular cells, 1,000,000 training rows, rank 64, reconstruction gain 1.02 and total normalized error 0.05. Thresholds belong to a versioned qualification profile and are not target-host measurements.

The strict predictor is logarithmic in cell count after canonical artifact construction. Benchmark training sort/group cost, peak memory, cold index validation, supported lookup, OOD rejection and target-device inference separately.

## 6. Concrete verification cases

- OP-01: sensor construction and Bellman tables reproduce deterministic goldens.
- OP-02: bad applicability, geometry, shape, OOD or error budget disables the learned path.
- OP-03: high in-sample fit without future calibration, retention and unlearning remains insufficient.
- OP-04: model-generated rollouts remain synthetic and unsupported pairs abstain.
- OP-05: complete-grid training, unique source evidence and canonical indexed lookup are mandatory.

Every case maps to concrete Rust tests in `../../lane-e/TEST_TRACEABILITY.json`. OP-05 is part of the authoritative operation set and may not be hidden as a supplemental operation.

## 7. Integration, rollback and capability ceiling

Operator input should consume a self-verifying ledger snapshot receipt and current artifact-withdrawal frontier. NDU may consume bounded continuation values but does not replace the world model. Rollback loads a complete compatible tuple under current revocations and never silently bypasses DAG predecessors.

Immediate revocation and stop remain effective. Preserve every external gate; no producer self-evaluation, selection, process loading, promotion or release is authorized.

## 8. Native closure and remaining evidence

Repository-controlled coverage includes applicability, sensor geometry, deterministic Bellman reference, strict simplest-sufficient fitting, regularity/error budgets, action-conditioned dynamics, OOD rejection and cross-crate public API linkage. `../../../scripts/hepta-lane-e-closure.py` verifies the complete operation and test set; `.github/workflows/hepta-lane-e-gap-closure.yml` compiles, tests, lints and formats exact head and ordered merge.

The repository cannot self-issue independent mathematical review, real model/runtime identity, target-device measurements, future-time calibration/retention, live-world transitions, operator acceptance, selected-process loading, canary, promotion or release. Those exact-candidate receipts remain external.
