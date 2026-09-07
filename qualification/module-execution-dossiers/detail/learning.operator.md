# learning.operator: implementation design

Parent: `docs/modules/learning.operator/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-bellman-operator`.
Packages: `HBO-0-BELLMAN-OPERATOR-CONTRACTS`, `HBO-1-OPERATOR-SENSOR-CORE`, `HBO-2-BELLMAN-OPERATOR-SHADOW`, `BIO-3-WORLD-MODEL-PREDICTION-ERROR`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`build_sensor_core(design, applicability_profile) -> OperatorSensorCoreManifestV1`; `fit_transition(dataset, dynamics_profile) -> WorldModelCandidate`; `fit_value_operator(dataset, sensor_core, objective, profile) -> BellmanOperatorArtifactV1`; `predict_candidate(model, state, legal_action) -> OutcomeDistribution`. Transition/dynamics estimation and continuation-value estimation have separate artifacts, losses and evaluations.

## 3. State records and transaction design

No production source writer. Training reads immutable ledger-bound datasets and writes candidate artifacts through learning.artifacts. Sensor cores are fixed versioned designs, not replay caches. Artifacts bind axis partition, conditioning snapshot, model and dataset lineage, normalized units, rank/architecture, code/runtime/device, error budget, applicability certificate and predecessor.

## 4. Deterministic algorithm and scheduling

Partition smooth, jump and hard axes; reject unsupported ellipticity/regularity rather than inject noise into hard state; construct deterministic farthest-point sensors; run scalar/tabular monotone reference; train the simplest sufficient direct value/action-gap candidate; measure approximation, reconstruction, optimization, statistics and rollout errors separately. Residual mode is allowed only on the supported near-greedy subset. World models additionally predict calibrated one/multistep action-conditioned transitions and flag OOD.

## 5. Capacity and performance profile

Canonical smooth dimensions <=32, sensor count <=4096, rank <=64, reconstruction gain <=1.02 and total normalized error <=0.05 where applicable. Training compute/epochs/memory and simulator calls are manifest budgets. A coordinate failing assumptions uses a qualified simpler fallback, not a fabricated certificate.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- OP-01: analytic sensor/Bellman table reproduces canonical Q32 goldens.
- OP-02: degenerate diffusion, bad mesh ratio or excessive reconstruction gain disables the learned path.
- OP-03: a high in-sample fit with poor future calibration/retention fails evaluation.
- OP-04: model-generated rollouts remain synthetic and cannot become independent factual outcome evidence.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

NDU consumes bounded continuation values but does not replace the world model. C1 may use the simpler baseline allowed by its registered package; do not silently bypass existing DAG predecessors. Rollback loads a complete compatible operator/sensor tuple under current revocations.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
