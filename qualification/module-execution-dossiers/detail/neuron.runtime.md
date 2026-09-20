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

- **Canonical owner path:** `NeuronRuntimeHost::tick` in [codex-rs/hepta-neuron/src/owner_runtime.rs](../../../codex-rs/hepta-neuron/src/owner_runtime.rs) is the product-facing source boundary. It freezes a complete `SelectedNeuronModelManifestV1`, revalidates current model/input/NDU/modulator/calibration lineage on every tick, computes calibration/OOD/resources/receipts before state mutation, durably prepares the exact result, commits the exact sparse successor, durably terminalizes the operation, revalidates lineage again, advances the independent witness, then acknowledges. `runtime::LegacyNeuronRuntimeHost` is compatibility-only.
- **Exact operation recovery:** [codex-rs/hepta-neuron/src/operation.rs](../../../codex-rs/hepta-neuron/src/operation.rs) stores canonical result bytes and the exact required-lineage set in a separate HPTNOP01 journal. Prepared-without-state is aborted; state-with-matching-prepared is committed; mismatched/untracked state fails closed. Identical retry returns the exact durable result without model re-execution. One non-aborted operation identity is allowed per logical sequence.
- **Complete model identity:** [codex-rs/hepta-neuron/src/model_manifest.rs](../../../codex-rs/hepta-neuron/src/model_manifest.rs) binds encoder/head, tokenizer, preprocessor, quantization, backend, device, runtime binary, SBOM, license and OOD detector into the generation/checkpoint identity. Same encoder/head with any substituted runtime component is rejected.
- **State and witness:** [codex-rs/hepta-neuron/src/journal.rs](../../../codex-rs/hepta-neuron/src/journal.rs) persists deterministic sparse state; [codex-rs/hepta-neuron/src/witness.rs](../../../codex-rs/hepta-neuron/src/witness.rs) retains independently checksummed acknowledged-history anchors. Recovery may advance the witness only after exact operation reconciliation and live lineage re-admission.
- **Canonical protocol/calibration:** [codex-rs/hepta-neuron/src/protocol.rs](../../../codex-rs/hepta-neuron/src/protocol.rs), [wire.rs](../../../codex-rs/hepta-neuron/src/wire.rs) and [calibration.rs](../../../codex-rs/hepta-neuron/src/calibration.rs) implement strict typed/canonical adapters and generation/model/detector-bound calibration/OOD. Missing or stale evidence abstains/fails closed.
- **Plasticity ancestry:** [codex-rs/hepta-neuron/src/plasticity.rs](../../../codex-rs/hepta-neuron/src/plasticity.rs) maps every eligibility coordinate exactly once, uses explicit bounded low-dimensional modulator broadcast and trust regions, and directly binds selected artifact, generation, parameter manifest, window, update rule and predecessor to the sufficient-statistics digest. It never mutates current weights/topology.
- **Qualification surfaces:** [resources.rs](../../../codex-rs/hepta-neuron/src/resources.rs) summarizes externally observed p50/p95/p99/allocation/checkpoint/queue/write-amplification samples; [qualification.rs](../../../codex-rs/hepta-neuron/src/qualification.rs) executes deterministic lesions and binds preregistered future/retention/unlearning/evaluator evidence. These surfaces do not manufacture measurements or efficacy.
- **Product composition source:** [codex-rs/hepta-intelligence/src/neuron_runtime_port.rs](../../../codex-rs/hepta-intelligence/src/neuron_runtime_port.rs) exposes an object-safe authority-free owner port. [codex-rs/hepta-agentd/src/config.rs](../../../codex-rs/hepta-agentd/src/config.rs), [state.rs](../../../codex-rs/hepta-agentd/src/state.rs) and [runtime.rs](../../../codex-rs/hepta-agentd/src/runtime.rs) hold that port in the real Agentd daemon and fence calls before and after the owner boundary. This proves repository source composition, not deployed activation or a selected real encoder.
- **Source tests:** [closure_tests.rs](../../../codex-rs/hepta-neuron/src/closure_tests.rs) includes prepare→state, state→terminal, terminal→witness, ack-loss, model-substitution, tick-time revocation and recovery-revocation cuts; [wire_tests.rs](../../../codex-rs/hepta-neuron/src/wire_tests.rs), [qualification_tests.rs](../../../codex-rs/hepta-neuron/src/qualification_tests.rs), [sparse_tests.rs](../../../codex-rs/hepta-neuron/src/sparse_tests.rs), [journal_tests.rs](../../../codex-rs/hepta-neuron/src/journal_tests.rs) and [journal_anchor_tests.rs](../../../codex-rs/hepta-neuron/src/journal_anchor_tests.rs) cover their bounded surfaces. Agentd composition is exercised by [state_isolation_tests.rs](../../../codex-rs/hepta-agentd/src/state_isolation_tests.rs). Test identity is not an execution receipt.
- **Remaining repository-controlled work:** run exact-head and deterministic synthetic-merge qualification; add governed archival/retention before the bounded operation-result journal can support an indefinitely long-lived host; either implement/qualify distinct temporal/activation dimensions plus per-population competition or preserve the narrower native Q24 deployment profile.
- **External/empirical gates:** independently select and qualify a concrete encoder/head/runtime/device tuple; collect target-host and physical power-loss measurements; execute preregistered future/retention/lesion/deletion-non-resurrection evidence; obtain independent semantic/security acceptance, canary, promotion and release. No source test satisfies these gates.
