# learning.operator: implementation design

Parent: `docs/modules/learning.operator/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: deterministic reference, simplest-sufficient tabular learner and action-conditioned world-model source candidate implemented; current exact-head and synthetic-merge CI determine source qualification, while real-model efficacy and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-bellman-operator`.
Packages: `HBO-0-BELLMAN-OPERATOR-CONTRACTS`, `HBO-1-OPERATOR-SENSOR-CORE`, `HBO-2-BELLMAN-OPERATOR-SHADOW`, `BIO-3-WORLD-MODEL-PREDICTION-ERROR`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Existing compatible APIs remain available; no operation creates another authority or execution spine.

## 2. Public operations and contract details

`build_sensor_core(design) -> OperatorSensorCoreManifestV1`; structural compatibility APIs `validate_applicability_certificate`, `admit_operator_regularity`, `fit_transition_model` and `fit_tabular_operator`; qualification APIs `validate_applicability_with_signed_evidence_v2`, `admit_operator_regularity_with_signed_evidence_v2`, `verify_tabular_operator_plan_v2 -> fit_tabular_operator_verified_v2`, and `verify_world_model_dataset_v2 -> fit_transition_model_verified_v2`; owner-derived terminal APIs `freeze_terminal_cell_from_owner_v1`, `freeze_terminal_cell_from_signed_owner_v2` and `fit_terminal_cell_from_owner_v1`; prediction APIs remain deny-all and synthetic. These native records are bounded implementation profiles, not canonical wire-schema adapters; the full registered contract requirements remain in `docs/contracts/PROTOCOL_SCHEMAS.json` and the parent technical document.

The original `train` function remains a compatibility alias for `build_targets`; it is explicitly a target builder, not a neural trainer. The canonical tabular fit itself rejects duplicate underlying evidence. Generic dataset-bound V2 training checks `DatasetSnapshotReceiptV3` self-consistency and exact source-record membership, including cardinality, before creating opaque verified input types. This does not authenticate the freeze issuer, derive caller-supplied targets or check current owner revocations; qualification hosts must supply those checks. Structural evaluator fields alone are not independent evidence: qualification applicability and regularity consume signed generator/evaluator attestations verified by the ledger-owned `LearningEvidenceVerifierV1`.

The terminal profile instead derives real terminal targets and action labels from current owner events. Its V1 freezer requires already trusted receipt provenance. The signed-owner V2 freezer asks the actual `LedgerWriter` to authenticate the exact evaluator-attested freeze request and derive its complete current source cut. Fitting rechecks active records, owner trust and forward time; for signed-owner V2 it also revalidates the retained original attestation's expiry, credential validity and scheduled revocation at fit time. This constant-state terminal table does not implement general Bellman dynamics or grant selection authority.

## 3. State records and transaction design

There is no production source writer. Training reads bounded datasets and emits deny-all candidate values for `learning.artifacts`. Sensor cores are fixed versioned designs, not replay caches. Current native tabular payloads bind data/profile/sensor identities and retained cell statistics; the artifact owner supplies the manifest and predecessor boundary. The full operator contract additionally requires axis partition, conditioning, model/runtime/device, normalized units, complete error budget and applicability lineage. Native payload presence alone does not establish that full contract integration.

The tabular learner requires a complete canonical sensor-by-action grid and a minimum sample count for every cell. It stores per-cell mean, minimum, maximum, sample count and evidence digest. Missing or underfilled cells and relabelled duplicate evidence fail. `verify_tabular_operator_plan_v2` checks receipt self-consistency, objective/dataset identity and exact equality between training evidence and the receipt's source-record set before producing an opaque input accepted by `fit_tabular_operator_verified_v2`. Issuer authenticity, complete owner-cut provenance, current revocations and target derivation remain host obligations at this generic boundary. Predictions outside the fitted grid fail rather than extrapolate.

## 4. Deterministic algorithm and scheduling

Partition smooth, jump and hard axes; reject unsupported ellipticity or regularity rather than inject noise into hard state; construct deterministic farthest-point sensors; measure fill distance, separation radius and mesh ratio; run the complete tabular Bellman reference; fit the simplest sufficient tabular candidate; and measure rank, reconstruction, shape, OOD and complete error budget separately.

The action-conditioned world-model baseline groups immutable observed samples by state/action, rejects relabelled duplicate evidence, publishes exact Q32 branch distributions that sum to one and rejects unsupported pairs. Qualification uses `verify_world_model_dataset_v2` so rows are bound to the exact frozen dataset receipt before fitting. Every prediction is marked synthetic. A model prediction cannot become an independent factual outcome.

A later neural or low-rank tensor model must use a separately reviewed training profile and must beat or justify itself against the deterministic/tabular reference. Source presence alone cannot bypass applicability, future calibration, retention or rollback gates.

## 5. Capacity and performance profile

Canonical smooth dimensions are at most 32, sensor count at most 4096, action count at most 128, measured rank at most 64, reconstruction gain at most 1.02 and total normalized error at most 0.05. The tabular grid is bounded to 262144 cells and its training rows to 1000000. The world-model baseline is separately bounded by its state/action and branch limits. Training compute, memory and simulator calls remain profile budgets.

These are source bounds, not target-host measurements. A coordinate failing assumptions uses a qualified simpler fallback, not a fabricated certificate.

## 6. Concrete verification cases

- OP-01: the six-cell `HBO-GV-001` sensor/Bellman table reproduces the specified separately quantized Q32 reward and continuation inputs, targets, greedy actions and gaps in `hbo_gv_001_uses_quantized_reward_and_continuation_inputs`; input permutation produces the same receipt.
- OP-02: degenerate diffusion, bad mesh ratio or excessive reconstruction gain disables the learned path.
- OP-03: a high in-sample fit with poor future calibration/retention fails evaluation.
- OP-04: model-generated rollouts remain synthetic, unsupported pairs abstain and relabelled duplicate world-model evidence rejects.
- OP-05: canonical tabular fitting is deterministic and complete-grid, and both default and strict V2 admission reject relabelled duplicate evidence.
- OP-06: generic dataset-bound fitting verifies receipt self-consistency and exact source membership; the signed-owner terminal entrypoint derives the authenticated current owner cut. Persisted candidates require an independent pin and separate-process reload/rollback behavior.

Every case is mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`. Additional learned-grid tests verify order independence, complete-cell admission, minimum samples and domain-bounded prediction.

## 7. Integration, rollback and capability ceiling

NDU consumes bounded continuation values but does not replace the world model. An explicit Agentd `PinnedCognitiveRanker` already composes a selected, pinned `LoadedTabularOperatorV1` into the cognitive read-ranking boundary and revalidates the current artifact registry/revocation view on every read. That is a real read-only consumer, not the default training/evaluation/selection loop and not evidence of longitudinal benefit. C1 may use the simpler baseline allowed by its registered package; it must not silently bypass existing DAG predecessors. Rollback loads a complete compatible operator/sensor tuple under current revocations.

The explicit `AgentdSharedReplayHostV1::train_signed_owner_v2` entrypoint now composes signed-owner freezing with the existing exact Replay source-support checks and terminal fit. Its private helper consumes the original frozen input, retaining the attestation through fit; the compatible `train` entrypoint still requires trusted V1 receipt provenance. Both retain the existing artifact loading, source permission and ledger revalidation boundaries. The updated async source test exercises this route, but this dossier does not attest that its full integration execution has completed.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `build_targets` in [src/lib.rs](../../../codex-rs/hepta-bellman-operator/src/lib.rs); canonical evidence-unique tabular fitting in [src/learned.rs](../../../codex-rs/hepta-bellman-operator/src/learned.rs); action-conditioned world-model fitting in [src/world_model.rs](../../../codex-rs/hepta-bellman-operator/src/world_model.rs); signed applicability/regularity admission in [src/authenticated.rs](../../../codex-rs/hepta-bellman-operator/src/authenticated.rs); dataset-receipt-bound training in [src/dataset_bound.rs](../../../codex-rs/hepta-bellman-operator/src/dataset_bound.rs); and compatible receipt-based or signed-owner freezing followed by owner-revalidated terminal fitting in [src/owner_terminal.rs](../../../codex-rs/hepta-bellman-operator/src/owner_terminal.rs).
- **State and recovery:** Pure candidate artifacts bind immutable data/profile/sensor identities. encode_tabular_payload_v1 and LoadedTabularOperatorV1 add bounded persisted candidate encoding and independently pinned, once-validated prediction. Storage and selection remain with learning.artifacts and its host. train is a compatibility alias for target construction; the separate tabular learner requires a complete supported sensor/action grid and retains per-cell sample statistics.
- **Source tests:** [reference_tests.rs](../../../codex-rs/hepta-bellman-operator/src/reference_tests.rs), [learned_tests.rs](../../../codex-rs/hepta-bellman-operator/src/learned_tests.rs), [world_model_tests.rs](../../../codex-rs/hepta-bellman-operator/src/world_model_tests.rs), [authenticated_tests.rs](../../../codex-rs/hepta-bellman-operator/src/authenticated_tests.rs), [dataset_bound_tests.rs](../../../codex-rs/hepta-bellman-operator/src/dataset_bound_tests.rs), [loaded_tests.rs](../../../codex-rs/hepta-bellman-operator/src/loaded_tests.rs) and the cross-owner [terminal_cell_owner.rs](../../../codex-rs/hepta-agentd/tests/terminal_cell_owner.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md](../../../codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md), [docs/learning/HOLDER_BELLMAN_SPEC.md](../../../docs/learning/HOLDER_BELLMAN_SPEC.md).
- **Remaining work:** Canonical wire adapters and their conformance tests, and default freeze/training/evaluation/selection/new-process-load composition are repository implementation work. A neural/tensor model is optional unless the simplest-sufficient profile fails the objective. Target-host/device measurements, independent scientific applicability review, real future calibration/retention/live-world validation and operator acceptance remain separate evidence gates; signatures authenticate attestations but do not self-certify scientific truth.

## 9. Native closure and remaining evidence

Repository-controlled source coverage includes structural and signed applicability/regularity admission, fixed finite-design sensor geometry, deterministic Bellman reference, evidence-unique tabular fitting, receipt self-consistency and exact membership checks, signed-owner terminal freezing and revalidation, action-conditioned dynamics, pinned persisted loading and OOD rejection. `../../../scripts/hepta-lane-e-closure.py` verifies symbol and test mappings, while `.github/workflows/hepta-lane-e-gap-closure.yml` supplies exact-head and synthetic-merge compilation, tests, strict lint and formatting gates. Existing separate-process reload fixtures demonstrate bounded candidate loading; selecting a qualified candidate and composing that load into the default loop remain repository work.

The repository cannot self-issue independent mathematical review, target device measurements, future-time calibration/retention, live-world transition evidence, operator acceptance, canary, promotion or release. Runtime adapters and model identity binding can be implemented here, while claims about real runtime/device execution still require observed evidence. These external capability gates remain open until their owners provide exact-candidate receipts; source composition and wire conformance are separately tracked implementation gaps.
