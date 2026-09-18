# neuron.runtime: implementation design

Parent: `docs/modules/neuron.runtime/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: canonical owner host, Q24 sparse dynamics, witnessed persistence/rotation/rebuild, strict Neuron wire adapters, calibration/OOD application and next-snapshot plasticity statistics are implemented in the source candidate; remaining concrete model/product/empirical gates are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented owner path:** `NeuronRuntimeHost::tick` in [codex-rs/hepta-neuron/src/runtime.rs](../../../codex-rs/hepta-neuron/src/runtime.rs) accepts canonical typed input, invokes a required `FrozenModelExecutor`, validates exact model/runtime identity, commits through `SparseJournal`, applies qualified calibration/OOD, and advances an independent recovery witness before acknowledgement. `sparse_tick` remains the pure Q24 mechanism.
- **Persistence and recovery:** [codex-rs/hepta-neuron/src/journal.rs](../../../codex-rs/hepta-neuron/src/journal.rs) and [codex-rs/hepta-neuron/src/witness.rs](../../../codex-rs/hepta-neuron/src/witness.rs) provide bounded CAS persistence, acknowledged-history recovery, lost-witness suffix reconciliation, continuation-segment rotation and fail-closed deletion rebuild. A failed partial rebuild is poisoned.
- **Canonical protocol bridge:** [codex-rs/hepta-neuron/src/protocol.rs](../../../codex-rs/hepta-neuron/src/protocol.rs) and [codex-rs/hepta-neuron/src/wire.rs](../../../codex-rs/hepta-neuron/src/wire.rs) bind `NeuronRuntimeConfigV1`, `NeuronTickInputV1`, `NeuronTickReceiptV1`, `LocalModelRuntimeReceiptV1` and `NeuronSignalReceiptV1`. The effective host identity combines canonical config with the exact native sparse profile. Unsupported per-population competition fails closed rather than silently degrading to global top-k.
- **Calibration and plasticity:** [codex-rs/hepta-neuron/src/calibration.rs](../../../codex-rs/hepta-neuron/src/calibration.rs) applies generation/profile/model-bound calibration and OOD evidence after live lineage checks. [codex-rs/hepta-neuron/src/plasticity.rs](../../../codex-rs/hepta-neuron/src/plasticity.rs) requires explicit eligibility-to-parameter-group mapping, bounded low-dimensional modulator broadcast and trust-region next-snapshot sufficient statistics; there is no implicit broadcasting or current-run weight mutation.
- **Resource qualification surface:** [codex-rs/hepta-neuron/src/resources.rs](../../../codex-rs/hepta-neuron/src/resources.rs) summarizes externally observed p50/p95/p99 latency, allocation, checkpoint size, queue age and write amplification. It does not manufacture target-host measurements.
- **Named consumer path:** [codex-rs/hepta-intelligence/src/neuron_runtime_port.rs](../../../codex-rs/hepta-intelligence/src/neuron_runtime_port.rs) consumes the owner host and converts its result to authority-free advisory/slow-path evidence. Its executable test uses the real owner host boundary, but this is not evidence of a deployed Agentd/Codex production caller.
- **Source tests:** [codex-rs/hepta-neuron/src/closure_tests.rs](../../../codex-rs/hepta-neuron/src/closure_tests.rs), [codex-rs/hepta-neuron/src/wire_tests.rs](../../../codex-rs/hepta-neuron/src/wire_tests.rs), [codex-rs/hepta-neuron/src/sparse_tests.rs](../../../codex-rs/hepta-neuron/src/sparse_tests.rs), [codex-rs/hepta-neuron/src/journal_tests.rs](../../../codex-rs/hepta-neuron/src/journal_tests.rs) and [codex-rs/hepta-neuron/src/journal_anchor_tests.rs](../../../codex-rs/hepta-neuron/src/journal_anchor_tests.rs) are test identities, not execution receipts for this documentation revision.
- **Remaining work:** provide and independently qualify a concrete local encoder/head driver that returns the actual Q24 drive/prediction tensors and exact weights/tokenizer/preprocessor/quantization/runtime/device evidence; bind the named consumer into the real product host; qualify any wider canonical profile such as distinct temporal/activation dimensions or per-population competition instead of weakening the native fail-closed profile; collect target-host resource measurements; and obtain preregistered ablation/lesion, future-window, retention, deletion non-resurrection and independent acceptance evidence before claiming adaptive intelligence or production activation.
