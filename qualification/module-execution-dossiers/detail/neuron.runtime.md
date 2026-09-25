# neuron.runtime: implementation design

Parent: `docs/modules/neuron.runtime/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: Q24 sparse dynamics, anchored journal and complete durable operation/result recovery implemented in source; remaining product composition, V2 migration and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Owner runtime:** `NeuronRuntime::tick` in [codex-rs/hepta-neuron/src/runtime.rs](../../../codex-rs/hepta-neuron/src/runtime.rs) composes exact model execution, pure Q24 successor computation, durable complete-result preparation, journal commit, calibrated/OOD disposition, resource receipt, independent witness reconciliation and durable completion. It remains authority-free and does not select, install, promote or release an artifact.
- **Inference-control binding:** `InferenceControlModelPort` in [codex-rs/hepta-neuron/src/inference_control.rs](../../../codex-rs/hepta-neuron/src/inference_control.rs) consumes the registered inference-control feature receipt and verifies the exact encoder/head/weights/runtime tuple before the neuron owner accepts drive/prediction values. [codex-rs/hepta-infer-worker-host/src/model_worker.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker.rs) provides the worker-side feature execution surface.
- **Durability and recovery:** `FileNeuronOperationStore` in [codex-rs/hepta-neuron/src/operation_store.rs](../../../codex-rs/hepta-neuron/src/operation_store.rs) freezes the complete V1 runtime configuration and persists the exact operation/result before state mutation. `SparseJournal` supports bounded successor segments and exact replay/reconciliation; `FileAnchorWitnessStore` in [codex-rs/hepta-neuron/src/witness.rs](../../../codex-rs/hepta-neuron/src/witness.rs) is the separate acknowledgement frontier. Recovery covers completed retry, prepared-result replay, first journal commit without a witness and witness-CAS acknowledgement loss without model reexecution. Missing operation history, unrelated frontiers and uncertain writes fail closed.
- **Adaptive state:** [codex-rs/hepta-neuron/src/plasticity.rs](../../../codex-rs/hepta-neuron/src/plasticity.rs) binds committed eligibility history to an independent low-dimensional modulator and explicit parameter-group projections, producing trust-region-bounded next-snapshot sufficient statistics only. It never mutates selected/current-run weights.
- **Deletion and evidence:** [codex-rs/hepta-neuron/src/deletion.rs](../../../codex-rs/hepta-neuron/src/deletion.rs) requires an exact successor generation and fail-closed no-state-reuse rebuild receipt for deleted/revoked lineage. [codex-rs/hepta-neuron/src/qualification.rs](../../../codex-rs/hepta-neuron/src/qualification.rs) exposes resource summaries and preregistered mechanism ablation transforms without converting supplied samples into independent empirical acceptance.
- **Canonical protocol surface:** [codex-rs/hepta-neuron/src/protocol.rs](../../../codex-rs/hepta-neuron/src/protocol.rs) projects the registered `NeuronRuntimeConfigV1`, `NeuronTickInputV1`, `NeuronTickReceiptV1`, `NeuronSignalReceiptV1` and `NeuronCheckpointV1` JSON boundaries with unknown-critical-field rejection. The checkpoint adapter derives summaries and predecessor identity from committed owner state and rejects a caller-forged predecessor.
- **Versioned target mechanism:** [codex-rs/hepta-neuron/src/population_v2.rs](../../../codex-rs/hepta-neuron/src/population_v2.rs) adds a pure V2 Q24 profile with distinct temporal/activation widths, explicit temporal-to-activation projection, complete registered populations and population-first then global top-k. The existing `SparseJournal` stays V1 replay-compatible; V2 durable migration is not silently implied.
- **Named callers:** [codex-rs/hepta-agentd/src/neuron_runtime.rs](../../../codex-rs/hepta-agentd/src/neuron_runtime.rs) is the compiled Agentd-owned long-lived source boundary over `NeuronRuntime + InferenceControlModelPort`; [codex-rs/hepta-intelligence/src/neuron_runtime.rs](../../../codex-rs/hepta-intelligence/src/neuron_runtime.rs) remains the typed intelligence caller. The Agentd daemon/run-lifecycle composition is owned by the separate `runtime.agentd` convergence line and is not yet activation or product-execution evidence.
- **Source tests:** [codex-rs/hepta-neuron/src/operation_store_tests.rs](../../../codex-rs/hepta-neuron/src/operation_store_tests.rs), [codex-rs/hepta-neuron/src/runtime_tests.rs](../../../codex-rs/hepta-neuron/src/runtime_tests.rs), [codex-rs/hepta-neuron/src/inference_control_tests.rs](../../../codex-rs/hepta-neuron/src/inference_control_tests.rs), [codex-rs/hepta-neuron/src/journal_anchor_tests.rs](../../../codex-rs/hepta-neuron/src/journal_anchor_tests.rs), [codex-rs/hepta-neuron/src/journal_segment_tests.rs](../../../codex-rs/hepta-neuron/src/journal_segment_tests.rs), [codex-rs/hepta-neuron/src/witness_tests.rs](../../../codex-rs/hepta-neuron/src/witness_tests.rs), [codex-rs/hepta-neuron/src/plasticity_tests.rs](../../../codex-rs/hepta-neuron/src/plasticity_tests.rs), [codex-rs/hepta-neuron/src/deletion_tests.rs](../../../codex-rs/hepta-neuron/src/deletion_tests.rs) and [codex-rs/hepta-neuron/src/qualification_tests.rs](../../../codex-rs/hepta-neuron/src/qualification_tests.rs), [codex-rs/hepta-neuron/src/protocol_tests.rs](../../../codex-rs/hepta-neuron/src/protocol_tests.rs), [codex-rs/hepta-neuron/src/population_v2_tests.rs](../../../codex-rs/hepta-neuron/src/population_v2_tests.rs) and [codex-rs/hepta-agentd/src/neuron_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/neuron_runtime_tests.rs). These are source tests, not target-host or longitudinal acceptance receipts.
- **Compatibility boundary:** the current durable mechanism remains the single-population/same-width `SparseConfig` Q24 profile. `PopulationSparseConfigV2` closes the pure target-mechanism source gap without rewriting V1 journal history; durable V2 migration/rollover requires its own versioned store/owner qualification.
- **Remaining repository work:** compose the long-lived `AgentdNeuronOwner` into the normal daemon run lifecycle with current selected-artifact, revocation/deadline/calibration-evidence providers and an actual consumer; define an explicit migration for any predecessor V1 journal lacking the operation sidecar; decide and implement the separately versioned V2/DecisionCell durable-state and effective-parameter migration if V2 is promoted; then run current exact-head, synthetic-merge and product-host qualification.
- **External evidence gates:** independently selected real-model execution, target-host latency/allocation/write-amplification measurements, future-window calibration/OOD/retention/unlearning evidence, independent semantic/security/statistical review, operator acceptance, canary, promotion and release remain separate. No source test self-certifies those gates.
