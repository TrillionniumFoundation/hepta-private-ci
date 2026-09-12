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

- **Implemented entrypoints:** `sparse_tick` in [codex-rs/hepta-neuron/src/sparse.rs](../../../codex-rs/hepta-neuron/src/sparse.rs); `SparseJournal` in [codex-rs/hepta-neuron/src/journal.rs](../../../codex-rs/hepta-neuron/src/journal.rs). Q24 sparse dynamics and optional anchored journal implemented.
- **State and recovery:** sparse_tick binds actual drive/prediction bytes, frozen config, scope/body/objective, sequence and monotonic clock. SparseJournal persists owned checkpoints through a host-authorized file and anchor; this is separate from the legacy Q32 step profile.
- **Source tests:** [codex-rs/hepta-neuron/src/sparse_tests.rs](../../../codex-rs/hepta-neuron/src/sparse_tests.rs), [codex-rs/hepta-neuron/src/journal_anchor_tests.rs](../../../codex-rs/hepta-neuron/src/journal_anchor_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-neuron/EXECUTION.md](../../../codex-rs/hepta-neuron/EXECUTION.md), [codex-rs/hepta-neuron/JOURNAL.md](../../../codex-rs/hepta-neuron/JOURNAL.md), [codex-rs/hepta-neuron/RECOVERY_ANCHOR.md](../../../codex-rs/hepta-neuron/RECOVERY_ANCHOR.md).
- **Remaining work:** Invoke and authenticate the actual encoder, qualify calibration/OOD, deletion rebuild and host recovery, and produce functional/longitudinal evidence before claiming adaptive intelligence.
