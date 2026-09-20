# neuron.runtime: implementation design

Parent: `docs/modules/neuron.runtime/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: Q24 sparse dynamics and optional anchored journal implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-neuron`.
Packages: `BIO-0-NEURON-INTUITION-CONTRACTS`, `NEU-1-LOCAL-MODEL-BAKEOFF`, `NEU-2-TEMPORAL-SIGNAL-RUNTIME`, `BIO-1-ELIGIBILITY-HOMEOSTASIS`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`tick(config, input, predecessor_checkpoint) -> CheckpointAndSignal`; `commit_tick(expected_anchor, successor) -> DurableTickReceipt`; `accumulate_plasticity(signal_history, independent_modulator, trust_region) -> PlasticitySufficientStatistics`. Use the existing sparse_tick and journal surfaces where compatible. Pure tick success is not a durable commit, model invocation or calibrated policy decision.

## 3. State records and transaction design

Own neuron_state_checkpoint and eligibility_trace_checkpoint. Checkpoints bind subject/scope, objective/body/config/model/normalization, monotonic sequence/time, recurrent state, sparse activation, moving activity, thresholds, eligibility and predecessor digest. Selected weights/topology are immutable artifact inputs. In-run bounded temporal/homeostatic state may evolve; selected parameter bytes may not.

## 4. Deterministic algorithm and scheduling

Validate all bindings and clock; update bounded recurrent state in Q24; apply registered inhibition; deterministic top-k positive competition with stable ties; update bounded activation average and threshold; update local eligibility; compute prediction error; emit signal/checkpoint; CAS-publish checkpoint and receipt atomically or through owner outbox. Eligibility is mapped to the declared parameter groups before low-dimensional modulation; implicit broadcasting is forbidden. Uncalibrated signals require slow path and cannot invent OOD confidence.

## 5. Capacity and performance profile

Canonical h<=256, z<=512 subject to the actual native profile, top-k 1%-20%, modulator<=8, state [-8,8], eligibility norm<=4, checkpoint<=1 MiB. Sparse native implementations with narrower bounds retain them. Measure tick/journal separately; real-encoder latency is not hidden inside a scalar fixture number.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- NEU-01: inhibition/top-k tie, homeostasis and eligibility goldens preserve exact Q24 semantics.
- NEU-02: two writers advancing one predecessor yield one commit and one conflict; restart reproduces the checkpoint.
- NEU-03: clock regression, model/body/scope mismatch and deleted-row replay reject before mutation.
- NEU-04: no-inhibition/no-homeostasis/no-eligibility/no-replay/shuffled-modulator lesions are tested on preregistered future and retention slices before biomimicry claims.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

A model digest alone does not prove encoder use; attach exact weights/tokenizer/runtime/device and a real consumer. SparseSignalReceipt.requires_calibration remains truthful until a qualified head exists. Rollback revalidates checkpoint/encoder/profile compatibility and current revocations.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Owner runtime:** `NeuronRuntime::tick` in [codex-rs/hepta-neuron/src/runtime.rs](../../../codex-rs/hepta-neuron/src/runtime.rs) composes exact model execution, the Q24 mechanism, durable journal commit, calibrated/OOD disposition, resource receipt and an independently retained acknowledgement witness. It remains authority-free and does not select, install, promote or release an artifact.
- **Inference-control binding:** `InferenceControlModelPort` in [codex-rs/hepta-neuron/src/inference_control.rs](../../../codex-rs/hepta-neuron/src/inference_control.rs) consumes the registered inference-control feature receipt and verifies the exact encoder/head/weights/runtime tuple before the neuron owner accepts drive/prediction values. [codex-rs/hepta-infer-worker-host/src/model_worker.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker.rs) provides the worker-side feature execution surface.
- **Durability and recovery:** `SparseJournal` supports bounded successor segments and exact replay/reconciliation; `FileAnchorWitnessStore` in [codex-rs/hepta-neuron/src/witness.rs](../../../codex-rs/hepta-neuron/src/witness.rs) is a separate locked, synced acknowledgement witness. Journal commit precedes witness publication; uncertain writes poison the handle rather than becoming success.
- **Adaptive state:** [codex-rs/hepta-neuron/src/plasticity.rs](../../../codex-rs/hepta-neuron/src/plasticity.rs) binds committed eligibility history to an independent low-dimensional modulator and explicit parameter-group projections, producing trust-region-bounded next-snapshot sufficient statistics only. It never mutates selected/current-run weights.
- **Deletion and evidence:** [codex-rs/hepta-neuron/src/deletion.rs](../../../codex-rs/hepta-neuron/src/deletion.rs) requires an exact successor generation and fail-closed no-state-reuse rebuild receipt for deleted/revoked lineage. [codex-rs/hepta-neuron/src/qualification.rs](../../../codex-rs/hepta-neuron/src/qualification.rs) exposes resource summaries and preregistered mechanism ablation transforms without converting supplied samples into independent empirical acceptance.
- **Named caller:** [codex-rs/hepta-intelligence/src/neuron_runtime.rs](../../../codex-rs/hepta-intelligence/src/neuron_runtime.rs) is a named source-composed caller over the owner runtime. This is not yet an activated Agentd daemon composition or product-execution receipt.
- **Source tests:** [codex-rs/hepta-neuron/src/runtime_tests.rs](../../../codex-rs/hepta-neuron/src/runtime_tests.rs), [codex-rs/hepta-neuron/src/inference_control_tests.rs](../../../codex-rs/hepta-neuron/src/inference_control_tests.rs), [codex-rs/hepta-neuron/src/journal_anchor_tests.rs](../../../codex-rs/hepta-neuron/src/journal_anchor_tests.rs), [codex-rs/hepta-neuron/src/journal_segment_tests.rs](../../../codex-rs/hepta-neuron/src/journal_segment_tests.rs), [codex-rs/hepta-neuron/src/witness_tests.rs](../../../codex-rs/hepta-neuron/src/witness_tests.rs), [codex-rs/hepta-neuron/src/plasticity_tests.rs](../../../codex-rs/hepta-neuron/src/plasticity_tests.rs), [codex-rs/hepta-neuron/src/deletion_tests.rs](../../../codex-rs/hepta-neuron/src/deletion_tests.rs) and [codex-rs/hepta-neuron/src/qualification_tests.rs](../../../codex-rs/hepta-neuron/src/qualification_tests.rs). These are source tests, not target-host or longitudinal acceptance receipts.
- **Compatibility boundary:** the current durable mechanism remains the single-population/same-width `SparseConfig` Q24 profile. The readiness target with distinct temporal/activation dimensions and population-first competition requires a separately versioned mechanism profile rather than silently changing replay semantics.
- **Remaining repository work:** compose the owner through the real `runtime.agentd` product path; implement strict canonical JSON adapters for the registered Neuron protocols including `NeuronCheckpointV1`; implement/qualify the multi-population `d_h != d_z` profile; then run current exact-head, synthetic-merge and product-host qualification.
- **External evidence gates:** independently selected real-model execution, target-host latency/allocation/write-amplification measurements, future-window calibration/OOD/retention/unlearning evidence, independent semantic/security/statistical review, operator acceptance, canary, promotion and release remain separate. No source test self-certifies those gates.
