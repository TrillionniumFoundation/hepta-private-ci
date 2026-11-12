# Frozen same-actor phase: ordinary entry and material inventory

## Finding

The frozen sources provide a real **public embedded-host composition path** for the original Root service and the same live daemon. Their internal code receives the original rights, installs A, retains the actual A learning source, runs original Learning, waits for real B inputs when Training produces a candidate, and installs C through the original publication and grant path. **The ordinary daemon main and Root CLI do not call these new entries.** This is an entry/material/deployment gap, not evidence that merely exporting the API executed A, B or C. [S01–S15]

The existing ordinary `--root-production-entry late-writer` main path remains implemented. It selects the older actual late-writer receiver; it does not select `AgentdOriginalSameActorPhaseStartupV1` or create the new typed host channels. The Root CLI still uses `PreparedHostAuthoritySession` and its existing fresh-session handoff/options. The new Root host provides the actual three-right sender internally, but an ordinary process launcher must invoke and feed that host. [S02, S11, S14–S17]

This report binds exact frozen overlay blobs to base `d9737937eaccccf2ed2f1f79444ddec6c10d0eea` / tree `2402c0f7605c1e6d23430c5aaeea8d08743cac59`. It is not an integrated-commit/native result. `ENTRY_INVENTORY.json` contains all 26 verified source blobs, byte counts and SHA256 values. There were no source/ref changes, h calls, native runs or checker executions.

## Actual entry surfaces

| Surface | Concrete entry | What exists | What ordinary deployment still must provide |
|---|---|---|---|
| Root | `PreparedRootSameActorQ24PhaseV1::{open,prepare_fresh_from_registered}` → `serve_original_same_actor_host` | Original service, fixed deadline, phase reservation, three-right writer/phase/scoped handoffs, one-shot Initial/Scoped/Current registration and acknowledgements. | Actual config/registration, daemon pidfd, Root CURRENT directory, Initial deployment, Model reservation, held Root pidfd, registered writer File, three datagram endpoints, consumer state root, Root command/ack channel owner. |
| Daemon | `AgentdOriginalSameActorPhaseStartupV1::from_process_environment` → `run_original_phase` | Original descriptor preflight, Starting comparison, actual Root rights/five lanes, original Config, Initial publication, required worker and original Launch.run. | Dedicated non-Root process/environment, actual Control/AppServer and Android Primary inputs, two additional phase datagrams, multithread runtime/arg0 setup and actual BusinessInputs. |
| Business host | `original_same_actor_phase_host_channel_v1` | Bounded in-process Tokio command Sender, event Receiver and worker endpoint; capacity 1..64. | A real consumer of events and producer of original typed material commands, plus ordinary signed ObjectiveStart submissions. |
| Default executables | Existing `main.rs` and `hepta-authority-host.rs` | Ordinary and late-writer startup; existing Root session/admin/deployment commands. | No invocation of either new phase entry or orchestration of the new host event/command sequence. |

Sources: S01–S04, S11–S17. Public reexports are present in the frozen parent modules and lib. The slice author's reported external caller sets for both new top-level entries are empty. This bounded review directly verifies absence in the two CLI files and original Startup branches; it does not claim a new exhaustive repository caller-checker run.

## Materials and real work at each boundary

1. **Root admission and Initial handshake.** The two trusted hosts must coordinate daemon `InputsOpened`, Root `Initial(original enrollment)`, the actual `InitialRegistered` acknowledgement, then daemon `InitialRootEnrolled`. That last notice orders the connection; it is not authority. The Root capability independently validates its original materials. Fresh filesystem deployment, actual Starting identity and original descriptor custody remain necessary. [S01–S03]

2. **A execution and Outcome.** BusinessInputs contains the real Artifact owner and selection, original Initial target/model, task Source/Cell files, fence/circuit/routes, worker/queue limits and clock, TaskLedger inputs, AuthBus trust/checkpoint, objective profile and Plasticity bootstrap. The installer performs actual Initial prepare/grant/publish and opens the original task runtime/ledger. `OriginalAOwnersInstalled` is not a submitted task or Ready receipt. A must enter through the original signed ObjectiveStart/Control route. The host later supplies an independently authenticated terminal Outcome and signed evidence, actual preparation/history/freeze materials. The controller closes A admission, waits for real tickets/pending work, accepts the real Outcome, creates Prepared, retains its original source and durably drains A. [S03–S07]

3. **Experience/Dataset and Trainer.** `OriginalAPrepared` exposes the actual Prepared Arc and its Root profile. Root must register that profile through `Scoped`. The daemon host must provide `OriginalCellQ24LearningInputsV1`: that same Prepared Arc, real source/receipt/training/local-decision journals and witnesses, existing keys/verifiers/policy, explicit Create/Recover and bounded capacities. Assembly checks pointer identity with the joined/scoped Prepared. The retained delivery drives the original outbox; the controller does not submit a duplicate request. There is no ordinary CLI loader for all these live owners. [S07, S08, S10, S18]

4. **Candidate Training → independent B.** The controller emits actual Training snapshot/material/readback, waits for one typed Evaluation command, installs those inputs against the same original cut, then awaits the original decision future. A legitimate TrainingNoUpdate follows its original decision path without waiting for B. Neither a Training event nor Installed state is B qualification. [S04, S09, S19–S24]

5. **Artifact, Selection and CURRENT.** After the actual decision, the host must supply either a real qualified publish request or the original authenticated retain/defer/no-update branch, then independent Selection inputs. Root must receive the exact Current enrollment after the real selection. The controller still consumes the original publication ticket and Root grant. A selection digest event is only an observation; it cannot replace those capabilities. [S02, S04, S09]

6. **C execution and feedback.** The host provides actual predecessor/target files, definition/source/model and fresh execution inputs. This phase requires Source Create and real OriginalLedger feedback Create. The original worker installs C; a separate signed ordinary ObjectiveStart must actually run it, followed by an independent terminal C Outcome and signed evidence. This is a same-actor/principal task transition under the original target checks, not an independent consumer/controller adoption. [S01, S03, S04, S09]

## How a real external host would do B

The word “host” here means code linked to the daemon-side typed entry, or a real external service integrated by that code. The returned mpsc event Receiver is not a new socket protocol. The opaque Training readback is not serialized authority for a remote process. Root has a separate in-process std mpsc command/ack channel. The bridge between these hosts and any separate B service must actually exist. [S02, S04, S20, S21]

The existing B APIs are sufficient to name the required operations; the phase does not supply the experiment:

- Retain the event Receiver from `original_same_actor_phase_host_channel_v1`; move its worker endpoint into BusinessInputs. Receive `OriginalTraining { snapshot, material, readback }` only after the controller has obtained the actual completed Training cut. Material exposes the actual native candidate completion; readback supplies the original Trainer provenance. [S04, S09, S19]
- Obtain and execute the real candidate and fixed-expert workloads, preserving their drained Cell journals and original task costs. Use `freeze_cell_learning_evaluation_plan_v1` with the original evaluation profile, temporal plans and comparison contract. It checks distinct actual owner cuts, same comparison task and frozen journals. [S23, S25]
- Use `CellEvaluationRunnerV1::evaluate_or_readback` with a real final-holdout provider, durable execution store and `OriginalCellEvaluationExecutionOwnerV1` carrying an already enrolled Evaluator key and independent witness. The plain unsigned `evaluate` result does not satisfy the original signed-execution requirement. [S24–S26]
- Produce authentic qualification evidence with `qualification_bundle` and `qualify_and_persist`, the actual verifier/current clock, evidence sink and required role/controller separation. The source checks the exact trained candidate and actual selected baseline. [S24–S26]
- Transfer those real resources in `OriginalCellQ24EvaluationInputsV1`, retaining the actual event Trainer readback (or the supported original pinned external Trainer), and send `Evaluation` once. The inputs include both journals, runner, execution store, temporal plans, qualification, context, evidence, timing, receipt file/witness and enrolled signer/key. Actual installation and subsequent Evaluation completion still validate them. [S09, S20–S22]

The comparison contract preserves matched parameter capacity, cumulative training budget and selective-update equality. Cumulative work includes inherited pretraining and charged candidate search; frozen cost coverage rejects missing stages, unknown outcomes and unknown required metrics, including mandatory Wall/CPU. Host-supplied IDs/digests alone do not authenticate this history. No change in this phase supplies missing costs or relaxes B. [S23, S24]

## Concrete missing edges and qualification impact

| Missing or unproven edge | Consequence |
|---|---|
| Ordinary process entry invoking the two new typed hosts with real inherited descriptors and owners | New public APIs are callable; ordinary deployment is not yet wired. |
| Actual event-consuming host, coordinating Root registration with daemon events | No ordinary A→Scoped→Current orchestration is demonstrated. |
| Real A objective, external Observer Outcome and source/training owner provisioning | No ordinary A/Experience/Dataset/Trainer acceptance follows from installed code. |
| Real B holdout/provider, matched actual journals/costs, enrolled independent evaluator and authentic qualification | Candidate-B cannot be counted from the enum, notification test or synthetic fixture. |
| Real Artifact/Selection producer, ordinary C objective and independent C Outcome | C installation and OriginalLedger availability do not prove a C workload or independent consumer. |
| Final phase-completion / physical owner-join acknowledgement | Startup explicitly returns an error even if generic Launch.run returns Ok; after C Outcome the controller keeps serving under the original deadline. This is not clean shutdown/restart acceptance. |
| Cross-incarnation retained-source contract and independent-consumer authorization | This same-live-actor path does not provide cold OS restart or a new principal/controller. |

Sources: S01–S10, S18–S26.

The original deadlines constrain the whole operation. Root captures its absolute limits before opening the phase; the daemon captures its earliest local limit before parsing and also applies the actual Root time binding. Later input, B wait or ACK cannot renew either limit. Root and daemon do not share an Instant value across processes. The current phase Startup supports the real Android Primary and expressly refuses Notes UI/Desktop combinations for this Circuit profile. [S01, S03, S17]

**Acceptance remains ordinary A / independent B / independent C = 0 / 0 / 0.** This inventory adds no native evidence. The frozen Work/B tests are component tests; the B notification fixtures use data-only snapshots and are not actual Trainer/B execution. An original gate passing on a later integrated source would establish that gate's result, not fill the external workload/deployment gaps above.

## Source record

The adjacent JSON source table records each S01–S26 full path, Git blob, exact UTF-8 length, SHA256 and whether it is a frozen overlay or original fixed-base source. All 26 exact strings were independently rehashed in V8. One failed lookup made while resolving a remembered short pin yielded NOT_FOUND and supplied no evidence; the intended source was then fetched by its fixed-base path and verified as S24. No original source or frozen delivery was modified.
