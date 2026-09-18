# learning.operator technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.operator`

**Owner:** `learning-platform`

**Deputy:** `qualification-plane`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `HBO-0-BELLMAN-OPERATOR-CONTRACTS`

This stable document is the implementation and operation guide for `learning.operator`. Normative identity, ownership, contract, data-authority and delivery facts remain in canonical JSON registries. Documentation readiness is not source qualification, product composition, activation, independent operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Train bounded Bellman/operator candidates in qualification space without online production mutation. The module provides deterministic reference construction, simplest-sufficient learned candidates, action-conditioned world-model candidates and deny-all qualification inputs. It does not own online policy selection or product writes.

The primary owner `learning-platform` controls the declared target root and is accountable for correctness, compatibility, replay integrity, resource bounds, test evidence and rollback. The deputy `qualification-plane` independently reviews contracts, authority checks, persistence/loading, resource limits and acceptance evidence. Cross-owner changes require an explicit co-owner or separate integration package.

Plane `qualification`, kind `trainer`, state model `stateful_shadow` and architecture role `slow_learner` define placement. Local optimization cannot be interpreted as global optimality or ownership of another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-bellman-operator`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-bellman-operator`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `learning.operator`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `learning.ledger`
- `learning.artifacts`
- `kernel.evidence`

Authoritative write domains: none.

Explicitly denied capabilities:

- `online_current_artifact_mutation`
- `production_write`

The module accepts only registered, bounded, versioned inputs. Missing authority, stale revisions, scope mismatch, digest mismatch, duplicate evidence, incompatible action domains and unsupported cells are hard failures. It never directly writes another owner's store.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, converting qualification evidence into deployment authority, or requiring a neural/tensor implementation when the simpler qualified candidate is sufficient.

## 4. Internal architecture and component decomposition

The bounded components are:

- immutable dataset/target admission;
- deterministic Bellman target and reference evaluator;
- applicability and sensor-core admission;
- replay-safe tabular learner;
- replay-safe action-conditioned world-model learner;
- candidate payload encoders;
- independently pinned immutable loaded predictors;
- regularity and statistical qualification admission;
- external artifact-owner integration;
- qualification-evidence acceptance package.

### Replay boundary

Evidence identity, not caller-controlled sample identity, is the replay boundary. `build_targets` rejects duplicate support digests. Public tabular and world-model fit wrappers reject duplicate evidence digests before sample counts, target statistics, transition counts or branch probabilities are computed. Relabelling one observation cannot make it contribute twice.

### Runtime candidate boundary

A public candidate struct is not an authenticated runtime object. Cross-crate inference uses `LoadedTabularOperatorV1` or `LoadedTabularWorldModelV1`; each is created only after independently pinned payload/model validation. Raw artifact predictors remain crate-internal implementation/test helpers and are not re-exported from `lib.rs`.

### Configuration and generation

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision/generation. Hidden mutable singletons, unbounded queues and implicit store fallbacks are prohibited.

## 5. Contracts, ports and compatibility

Current produced source contracts include:

- `BellmanOperatorArtifact`
- `TabularOperatorArtifactV1`
- `TabularWorldModelV1`
- `OperatorSensorCoreManifestV1`
- `OperatorRegularityAdmissionV1`
- `WorldModelQualificationAdmissionV1`
- bounded tabular/world-model candidate payloads.

Current consumed or bound contracts include:

- immutable learning dataset and evidence identities;
- artifact-owner current-selection and lineage pins;
- applicability/regularity profiles;
- independently produced world-model qualification assessment/profile;
- operator-acceptance frozen evidence and externally pinned trust policy.

The deterministic reference and public learned fitting paths require at least two actions. The tabular learner requires a complete canonical sensor-by-action grid and positive per-cell sample floor. Compatibility is additive only where registered.

The original `train` symbol is deprecated. It is a compatibility alias for `build_targets`, not a trainer. New code must use the explicit operation name. A genuine neural/tensor trainer, if later justified, receives a distinct immutable profile and API.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains: none.

Read-only dependencies include the learning artifact registry, credit/episode ledgers, unlearning lineage, sensor-core registry and qualification evidence.

Candidate persistence belongs to `learning.artifacts`. The Bellman crate only encodes bounded candidate bytes and validates independently selected pins. Tabular pins bind payload, training-artifact, objective, dataset, sensor-core, training-profile and generation identities. World-model pins bind the complete semantic payload digest, model digest, dataset digest and model identity. Corruption, truncation, trailing bytes, noncanonical order, invalid statistics, invalid probability/count totals or identity drift reject.

Rollback reopens an immutable compatible predecessor through the artifact owner under the current registry/revocation witness. Source tests exercise separate-process baseline/candidate/predecessor loading; this is engineering evidence, not product deployment authority.

## 7. Runtime, concurrency and transaction model

The native implementation is CPU/local deterministic code with no production writer. Fitters build deny-all candidate values from immutable inputs. Loaded predictors hold private immutable state after admission and perform repeated lookups without re-trusting a caller-supplied mutable artifact.

The qualification acceptance package owns its sidecar transaction boundary. It uses create-only/atomic private writes, a durable trusted-time watermark, nonce claim and final receipt. It rechecks trust policy and frozen evidence across signature verification to fail closed on concurrent change.

Shared concurrency and transaction requirements remain applicable at the artifact, evidence and acceptance owner boundaries.

## 8. Failure semantics, recovery and rollback

Fail-closed conditions include:

- duplicate sample identity or duplicate evidence/support digest;
- missing/underfilled grid cells or fewer than two actions;
- unsupported applicability or expired applicability evidence;
- exact sensor work exceeding the source budget;
- rank/gain/shape/OOD/error-budget breach;
- candidate payload/pin mismatch or corrupt/noncanonical payload;
- unsupported prediction cell/state-action pair;
- insufficient holdout/effective support/snapshot/future-window evidence;
- calibration/drift/confidence bound breach;
- qualification-acceptance trust/frozen-evidence/time/nonce mismatch.

Failure never causes online mutation or automatic fallback promotion. A simpler qualified predecessor/fallback must be selected by its owner. Rollback and revocation preserve lineage; no test in this module grants selection authority.

## 9. Security, privacy and threat controls

Owned threat entries:

- `Bellman_error_amplification`
- `off_policy_residual_blowup`
- `replay_contamination`

Controls now explicitly include evidence-digest replay admission across target construction, tabular fitting and world-model fitting; deny-all candidate authority; independent payload pins; bounded canonical decoding; exact-work admission; regularity/OOD admission; and frozen statistical-evidence binding.

Credentials do not enter learning datasets or general logs. Acceptance trust inputs are externally pinned and qualification-only. A hash computed from received bytes is not independent selection or admission.

Negative tests cover relabelled evidence replay, action-domain mismatch, payload tampering/truncation, unsupported predictions, future-window insufficiency, drift excess, denied authority and revoked artifact loading.

## 10. Performance, capacity and hot-path policy

Source ceilings include the registered dimension/sensor/action/rank/grid/sample bounds. In addition, exact sensor construction now estimates coordinate work before entering pairwise/farthest-point geometry. The estimate covers candidate-pair duplicate checks, candidate-to-selected updates and selected-pair separation. Work above the reviewed source ceiling rejects early.

Loaded tabular and world-model predictors validate once and keep private immutable canonical state for repeated lookup. This removes the former cross-crate pattern of repeatedly trusting and validating an arbitrary public artifact at prediction time.

All source ceilings are capacity controls, not selected-host measurements. Target CPU/GPU/device latency, memory and energy measurements remain external evidence.

## 11. Observability and operations

Offline/reference learning library. Bind immutable dataset/sensor/profile/evidence identities and emit candidates through the artifact owner. Distinguish deterministic reference, simplest-sufficient learner, world-model prediction and independent factual outcomes. Synthetic trajectories never supply independent production outcome evidence.

Operating references:

- `codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md`
- `qualification/module-execution-dossiers/detail/learning.operator.md`
- `docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`
- `qualification/lane-e/TEST_TRACEABILITY.json`

The operator-acceptance package may seal exact qualification evidence only. Its `automatic_transition=false` boundary must remain visible in operational dashboards and release logic.

## 12. Verification and qualification

Focused source references include:

- `src/lib_tests.rs` — deterministic target construction and duplicate-support rejection;
- `src/reference_tests.rs` — applicability, deterministic reference and regularity;
- `src/sensor_bounded.rs` — exact-work budget;
- `src/learned_tests.rs` — complete-grid fitting;
- `src/loaded_tests.rs` — pinned tabular validation and separate-process reload/rollback;
- `src/world_model_tests.rs` — action-conditioned deterministic baseline;
- `src/world_model.rs` — pinned world-model load/predict/tamper rejection;
- `src/world_model_qualification.rs` — effective-support/future/drift/confidence admission;
- `hepta-shadow-qualification/tests/lane_e_api_contract.rs` — cross-crate public-surface linkage;
- `hepta-shadow-qualification/tests/support/tabular_reload.rs` — artifact-owner reload/revocation integration;
- `hepta-operator-acceptance` tests — qualification-evidence ceremony/trust behavior.

Lane-E OP-01..OP-04 requirements are mapped to exact test functions in `qualification/lane-e/TEST_TRACEABILITY.json`. Exact-head and synthetic-merge CI, formatting, strict lint and all-target compilation remain required before source qualification is claimed.

Repository tests cannot self-create real future-calendar windows, selected-device measurements, live outcomes or independent acceptance.

## 13. Implementation sequence and work packages

Applicable packages:

- `HBO-0-BELLMAN-OPERATOR-CONTRACTS` — source implemented for current deterministic/tabular surface;
- `HBO-1-OPERATOR-SENSOR-CORE` — source implemented with explicit exact-work admission;
- `HBO-2-BELLMAN-OPERATOR-SHADOW` — source implementation present; live future/device qualification remains external;
- `BIO-2-REPLAY-CONSOLIDATION` — replay identity controls implemented on operator ingress; wider consolidation remains with owning modules;
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR` — deterministic baseline, pinned load and evidence admission implemented; live-world evidence remains external.

A neural/tensor candidate is a separately reviewed optional implementation profile, not an unfinished prerequisite by default. It becomes required only when objective/qualification evidence demonstrates that the simplest sufficient implementation is inadequate or another approved profile mandates it.

## 14. Activation, compatibility and retirement

Activation requires a named authenticated product caller through registered ports plus selected artifact, authority/configuration/resource checks and failure behavior. Shadow and qualification callers are not production callers.

The `hepta-operator-acceptance` ceremony has scope `qualification_evidence_only`; `automatic_transition=false`; its declaration grants no Enforce, promotion, outbound or retirement authority. Production activation must not reinterpret this receipt.

Retirement of raw compatibility paths requires all callers migrated. Raw predictor helpers are already non-public; `train` remains deprecated only for source compatibility and should be removed in a future breaking revision after repository callers are proven absent.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires current code, tests and a freshness-verified source snapshot. Qualification requires exact-candidate CI plus externally valid evidence for the claim being made. Product composition requires a named caller and selected-process loading. Independent operator acceptance, activation, canary, promotion and release are separate states.

Current candidate status is therefore: **repository source closure in progress under PR CI; production implementation remains false; product caller remains not composed; external live/future/device/independent-acceptance gates remain open.**

### Repository source-operation inventory (non-authoritative)

This inventory is navigation evidence for the current qualification candidate. The canonical source-location receipt remains Section 17; operation truth and freshness are machine-checked by `IMPLEMENTATION_MAP.json`.

| Operation | Native symbol | Source path | Tests |
|---|---|---|---|
| `build_targets` | `build_targets` | `codex-rs/hepta-bellman-operator/src/lib.rs` | `src/lib_tests.rs` |
| `fit_tabular_operator` | `fit_tabular_operator` | `codex-rs/hepta-bellman-operator/src/learned.rs` | `src/learned_tests.rs` |
| `fit_tabular_operator_strict_v2` | `fit_tabular_operator_strict_v2` | `codex-rs/hepta-bellman-operator/src/learned_strict.rs` | `src/learned_strict.rs` |
| `load_pinned_tabular_operator` | `LoadedTabularOperatorV1::from_pinned_payload` | `codex-rs/hepta-bellman-operator/src/loaded.rs` | `src/loaded_tests.rs` |
| `predict_loaded_tabular_operator` | `LoadedTabularOperatorV1::predict` | `codex-rs/hepta-bellman-operator/src/loaded.rs` | `src/loaded_tests.rs` |
| `validate_applicability_certificate` | `validate_applicability_certificate` | `codex-rs/hepta-bellman-operator/src/reference.rs` | `src/reference_tests.rs` |
| `build_sensor_core` | `build_sensor_core` | `codex-rs/hepta-bellman-operator/src/sensor_bounded.rs` | `src/sensor_bounded.rs`, `src/reference_tests.rs` |
| `evaluate_bellman_reference` | `evaluate_bellman_reference` | `codex-rs/hepta-bellman-operator/src/reference.rs` | `src/reference_tests.rs` |
| `admit_operator_regularity` | `admit_operator_regularity` | `codex-rs/hepta-bellman-operator/src/reference.rs` | `src/reference_tests.rs` |
| `fit_transition_model` | `fit_transition_model` | `codex-rs/hepta-bellman-operator/src/world_model.rs` | `src/world_model_tests.rs` |
| `load_pinned_world_model` | `LoadedTabularWorldModelV1::from_pinned_model` | `codex-rs/hepta-bellman-operator/src/world_model.rs` | `src/world_model.rs` |
| `predict_loaded_world_model` | `LoadedTabularWorldModelV1::predict` | `codex-rs/hepta-bellman-operator/src/world_model.rs` | `src/world_model.rs` |
| `admit_world_model_qualification` | `admit_world_model_qualification` | `codex-rs/hepta-bellman-operator/src/world_model_qualification.rs` | `src/world_model_qualification.rs` |
| `prepare_qualification_acceptance` | `prepare` | `codex-rs/hepta-operator-acceptance/src/lib.rs` | `src/lib_tests.rs` |
| `verify_and_seal_qualification_acceptance` | `verify_and_seal` | `codex-rs/hepta-operator-acceptance/src/lib.rs` | `src/lib_tests.rs`, `src/g5_trust_tests.rs` |
| `verify_qualification_acceptance_receipt` | `verify_receipt` | `codex-rs/hepta-operator-acceptance/src/lib.rs` | `src/lib_tests.rs` |

- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json`.
- Consumer callsites and durable owner stores remain explicit follow-up evidence when not listed above.
- Production implementation, runtime composition, independent acceptance, activation, and release remain false until their separate evidence gates pass.

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.operator` to primary lane `LANE-E-LEARNING`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.operator` is implemented by work package `HBO-0-BELLMAN-OPERATOR-CONTRACTS` in:

- `codex-rs/hepta-bellman-operator`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
