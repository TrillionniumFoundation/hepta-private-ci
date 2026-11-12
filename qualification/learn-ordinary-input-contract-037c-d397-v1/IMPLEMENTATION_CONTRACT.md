# Ordinary evaluated NoUpdate and cold recovery: implementation contract

Status: **audited production sources; ordinary qualification remains zero**.
This document does not claim that the ordinary launcher, a real external role deployment, or a daemon plus Root restart has passed. It distinguishes code that can be implemented with the current authority model from original deployment inputs that code cannot manufacture.

The production audit is pinned to `57b27c81d0d5321b873ee751fd0e58e1d905b988`, tree `3db894ee96d358c583bbf4ea15163a0d2bd96258`. The following source head, `d3977d9a1bed3e89952c576c45660b04ea674faf`, tree `57558558841da4a3209164d0033b903a553205d6`, changes test/QA/registry files, not this ordinary production chain. `SOURCE_MANIFEST.json` records each inspected physical file's exact Git blob, byte count, SHA-256 and immutable source URL; `EXACT_SRC_TREE.json` is the original 955-entry Agentd source tree used to check those blobs. Historical `094` or full RunStart examples are not used as current production inputs.

## 1. Conclusion and next executable slice

**A consuming producer and supervisor can be implemented inside the same `PreparedHostAuthoritySession`.** Its retained `HostAuthorityService` already owns the original issuer, Registry and protected Root directory. Such code must consume the real role channels and original authorizations, call the existing concrete stage constructors and `into_candidate_runtime`, retain the resulting runtime, and serve the actual V3 handle. It does not need a new signer, new lease, second issuer owner, or a public reconstruction of a private owner.

Two missing pieces are implementation work, not values that an operator should be asked to invent:

1. The session has no bounded consumer for a **late, already authenticated original candidate deployment** after actual A has completed. It does not yet retain or supervise the V3 runtime or publish its actual connected endpoint to the ordinary daemon.
2. Ordinary A has no production adapter for the **actual sealed Q24 task publication and its protected live CURRENT custody**. `PublishedCircuitFeatureTaskV1` retains the concrete guarded version/Artifact/FinalUse/current chain; it is not a serializable bootstrap record. Supplying its descriptor fields to `main` is insufficient. A same-process library caller can consume the actual object today. The ordinary Root/non-Root split additionally needs a purpose-limited live task/CURRENT transport or equivalent original host execution path, without transferring the protected Root directory into the daemon.

The smallest complete implementation therefore has two connected stages: establish the real A task capability and its ordinary runtime consumer; then install a late Root V3 producer/consumer using the **same** original session. Implementing only a setter on `AgentdConfig`, or only accepting a metadata DTO, would not close either stage. The narrow private-origin prerefusal described in section 8 is implemented separately and does not claim to close them.

## 2. Actual ordinary call chain and its first hard refusal

| Current call | Actual retained object / behavior | Missing productive edge |
|---|---|---|
| `main` → `AgentdProductionStartup::from_process_environment` | Claims original inherited descriptors before runtime work; ordinary and Root startup remain distinct. | No Q24 task publication or original ten-role bundle is received here. |
| `startup.receive().await` | Root startup connects the original five authority lanes with their original identity, pidfd and remaining lifetime. | No actual `OriginalCellQ24CandidateStageOwnersV1` is assembled. |
| Optional `RootLearningHandoffV1::connect` | Authenticated `HEPTA_ROOT_LEARNING_INPUTS_V1`; sealed schema 1/2 checkpoint profile, actual checkpoint restore, held Root pidfd. | This is a checkpoint client, not a schema-3 resident handle or a role bundle. |
| `config.with_root_learning_inputs(inputs)` | Stores the old actual checkpoint inputs for later assembly. | There is no ordinary caller supplying the concrete stages to `with_root_learning_stage_owners`. |
| `production.run(config, …)` | First checks `config.require_root_learning_assembled()`. | A partial old learning bootstrap is refused before ordinary dispatch. |
| `runtime::run` | Independently checks the same assembly requirement. | Both gates must remain; moving or deleting either is not a producer implementation. |

The current parsed primary production profiles are Android, Notes and Desktop. `production_launcher_inputs.rs` defines 19 original flags; none carries the Q24 published owner or the ten learning role streams. The Root CLI has original initialization, writer/learning registration and native/text/Notes session entry points. Its inherited-FD claims likewise do not yield these missing Q24/V3 capabilities. This is an inspection of those exact dispatch paths, not a claim that no external embedding application could call the public library APIs.

Existing `main` generation loading does not close this gap: `load_neuron_generation_process_bootstrap_v1` loads the Joint worker and ordinary generation journal/control channel. It does not return a Q24 `PublishedCircuitFeatureTaskV1`, actual Circuit Source, or an enrolled completed-A learning outbox.

Sources: [main](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57b27c81d0d5321b873ee751fd0e58e1d905b988/codex-rs/hepta-agentd/src/main.rs), [launcher](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57b27c81d0d5321b873ee751fd0e58e1d905b988/codex-rs/hepta-agentd/src/production_launcher.rs), [inherited inputs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57b27c81d0d5321b873ee751fd0e58e1d905b988/codex-rs/hepta-agentd/src/production_launcher_inputs.rs), [old handoff](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57b27c81d0d5321b873ee751fd0e58e1d905b988/codex-rs/hepta-agentd/src/root_production_learning_handoff.rs).

## 3. Earliest lawful original owners

### Root

`PreparedHostAuthoritySession::{prepare_fresh_from_registered, initialize_fresh, open}` retain one original `HostAuthorityService` together with the registered daemon identity and held original owner pidfd. The service was opened by the actual registered factory, not inferred from a profile. It already contains the issuer/Registry/Root custody required by `HostAuthorityService::{register_resident_learning_v3,recover_resident_learning_v3}`.

A new producer must be a consuming extension of that session's serving/launch path. It must not call `open_registered_issuer` a second time, reconstruct a `HostAuthorityService`, or hand the issuer/Registry/root directory back to an untrusted caller. The current session's `learning` field is the old registered checkpoint listener only; it does not contain the schema-3 resident runtime.

### A's guarded published task

The earliest ready task capability is `ReadyAgentdGenerationInitialV1<W>`, returned by either:

- `prepare_agentd_generation_initial_v1(actual_root, actual_authorities, actual_selection, actual_target, request)?.publish(&original_signed_final_use)`; or
- `recover_agentd_generation_initial_v1(actual_current, actual_authorities, actual_selection, actual_target, original_recovery_binding)` for an already published operation.

Its consuming `into_circuit_feature_task(definition, source)` creates the private `PublishedCircuitFeatureTaskV1`. The private chain contains the guarded generation journal, actual publication, concrete `LiveGenerationCurrent`, retained original selection, Artifact service and consumed FinalUse witness. `LiveGenerationCurrent` checks the real protected CURRENT, revalidates the selected Artifact and verifies the retained FinalUse, then reads CURRENT again after the authority/Artifact I/O.

`CircuitQ24TaskProfileV1<SW,CW>` consumes this sealed task plus actual Source/Cell journals, witnesses, inference control, fence, circuit/routes, original bundle/model, bounds and clock. `circuit_q24_task_channel_v1` opens the actual Source and Cell and returns the runtime bootstrap; `AgentdConfig::with_q24_circuit_task_profile` installs it. These are real mechanisms. No ordinary binary producer currently supplies their required original capability.

The protected `NeuronGenerationCurrentOwnerV1` is a concrete Root owner, not an RPC descriptor. Passing its raw directory/FD custody into the non-Root daemon would defeat the original protection. A remote consumer must receive an authenticated, purpose-limited live capability implemented by the original owner; it cannot reconstruct `PublishedCircuitFeatureTaskV1` from public JSON or a callback returning CURRENT values.

Sources: [session](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57b27c81d0d5321b873ee751fd0e58e1d905b988/codex-rs/hepta-agentd/src/authority_host_session.rs), [initial publication](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57b27c81d0d5321b873ee751fd0e58e1d905b988/codex-rs/hepta-agentd/src/neuron_generation_initial.rs), [live CURRENT](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57b27c81d0d5321b873ee751fd0e58e1d905b988/codex-rs/hepta-agentd/src/neuron_generation_update_live.rs), [Q24 task assembly](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57b27c81d0d5321b873ee751fd0e58e1d905b988/codex-rs/hepta-agentd/src/circuit_q24_task_profile.rs).

## 4. Exact input contract and supplying role

| Required input | Exact existing type / origin | Who must supply the original | What production code can do |
|---|---|---|---|
| Original Root session | `PreparedHostAuthoritySession` containing the same `HostAuthorityService` | Existing trusted registered Root startup | Consume it and retain its owners throughout the new serving scope. No second open. |
| Guarded A task | `ReadyAgentdGenerationInitialV1<W>` → `PublishedCircuitFeatureTaskV1` | Original generation publisher with protected CURRENT, real Artifact selection and original FinalUse | Add the actual consuming A bootstrap/remote task capability and install it in ordinary runtime. |
| A's original durable files/control | `CircuitQ24TaskFilesV1<SW,CW>`, `DurableInferenceControl`, `TaskFlowFence` | Trusted task host / existing file-custody deployment | Consume once; choose explicit Create or Recover; reject missing/partial history. |
| Exact source/profile/model | `CircuitQ24TaskProfileV1`, selected bundle, `Arc<LoadedCellQ24ModelV1>` | Actual selected model loader and registered Circuit task host | Validate component equality, fixed task/run and NDU source profile; never relabel full RunStart. |
| Original Material configuration | `OriginalCellQ24MaterialReceiptConfigV1` with initial cut, frozen scope, Dataset rule/plan, signed freeze, original signer trust and verifier | Experience/Dataset owners after actual A publication and signed intake | Fully validate it; code cannot sign the freeze or synthesize A completion. |
| Original role transports | `OriginalCellQ24CandidateStageStreamsV1` | Original external role-host deployment, addressed to the final Root process | Consume each existing connected stream, held pidfd, peer incarnation and remaining deadline; use existing constructors. |
| Independent B/retention registration | `OriginalCellEvaluationPanelRegistrationV1` and its actual separately supplied Evaluator host | Registered independent evaluator deployment, fixed before candidate evaluation | Verify exact primary/retention plan/profile; metadata alone does not instantiate B. |
| Candidate baseline | `Arc<LoadedCellQ24ModelV1>` with components equal to the original selected bundle | Actual immutable model files / host loader | Retain the same loaded baseline; do not fabricate a bundle identity. |
| Fresh Root resident authorization | `RootResidentLearningProfileV3` containing original signed intent and exact resident lease | Original Root issuer/Registry provisioned for `runtime.learning.resident-admission.v3` | Validate full scope/trust/original expiry; register actual protected record and consume fresh stages. |
| Cold authorization | Same original profile plus `RootResidentLearningReadbackAuthorizationV3` | Original Root issuer/Registry provisioned separately for `runtime.learning.resident-readback.v3` | Open existing state only, consume recovered stages, never issue a fresh continuation. |
| A enrollment | `AgentdRootResidentEnrollmentV3` + actual `AgentdRootResidentLearningClientV3` | Ordinary config creates the bounded enrollment receiver; original Root producer supplies its live channel | Perform actual preflight, durable A claim, then Admit; only final fully authenticated evidence can retire A's outbox. |

### Ten channels are ten original capabilities, not ten paths

The common seven channels are Experience, Dataset, Trainer, Selector, retained Version, NextUse/C observer and C completion-readiness. Candidate adds the same Trainer's candidate-material read channel, independent Evaluator, and Model channel. The current Candidate constructor requires all ten, including Model even when the desired path is evaluated NoUpdate. A new producer must not weaken that constructor based on a desired negative result.

Experience/Dataset/Trainer/Selector/NextUse/Evaluator/Model peers use `OriginalCellQ24NoUpdatePeerStreamV1`; Version and completion use `OriginalCellQ24NoUpdateTaskStreamV1`. Each includes an existing connected stream, pinned peer identity, an already held original pidfd and bounded original timeout/lifetime. The final Root process is the consumer. The public command-channel constructor rejects the same UID, same process, PID zero, invalid incarnation, timeout above 30 seconds or lifetime above 300 seconds. Evidence/readiness lanes keep their stricter purpose-specific 500 ms exchange limits. No factory may reopen a PID, reconnect, reset request counters, or renew a used channel.

For one ready Trainer, the four-connection semaphore is shared across all purposes. The implemented Version/S/C closed factories share the same retained T/B command clients; a producer must use those factories, not open an extra fifth Trainer connection. A frame-budget audit must also cover all transitive Material/Source reads, not merely count Root commands. This contract does not claim those complete runtime budgets have passed a real ordinary deployment.

### Grant/lease purposes cannot be inferred from generic Root ownership

The resident lease's `operation_class` must equal its exact resident destination/purpose. Generic `DeploymentFinalUseIssuer` issuance is separately protected by `runtime.agentd.production_operation`; an already existing generic issuing lease is not a resident admission/readback lease. Code may request an original grant only through a previously authorized provisioned original owner. It cannot create a missing policy or lease, change the intended subject/scope, or relabel an old lease. UID 0 is not authorization.

## 5. Minimal end-to-end implementation plan

The following names describe proposed code slices, not APIs claimed to exist.

### Slice A — actual A task capability, consumed by ordinary `main`

1. Add a private, concrete original-task host/consumer pair next to the existing Q24 task profile. The host consumes the actual `PublishedCircuitFeatureTaskV1` and retains its exact version/Artifact/FinalUse/CURRENT owners. The daemon-side type can only be constructed from the original connected peer, held Root pidfd, exact purpose/binding and complete authenticated original publication; no public raw-field constructor or caller CURRENT callback.
2. Keep Root protected CURRENT and Artifact/FinalUse custody on the original host. Expose only the fixed task's necessary live operations and original readbacks. Reuse the existing Source/Cell execution core; do not introduce a second signer or a parallel journal protocol.
3. Add a concrete branch to `AgentdProductionStartup::receive` which consumes this original task capability and installs the Q24 task bootstrap before `production.run`. The existing assembled gate remains after successful installation. The branch is reached only by a distinct authenticated producer purpose; it is not selected by an unauthenticated JSON claim.
4. Do not block startup waiting for an A-completed learning profile. A must first run using its authenticated original RunStart and publish its genuine Source/Cell/task receipt. Hold the late resident channel, then enroll after A completion.

This slice is implementable without new authority. It still requires the real input publication and original task files/control/model. A plain CLI path or public source descriptor is not a replacement. The existing inherited handoff facility can carry a new explicitly authenticated purpose without adding user flags, but the old V1 marker/FD count/schema must remain strict. The new receiver must claim each descriptor exactly once before privilege changes.

### Slice B — late producer inside the same prepared Root session

1. Introduce a non-Clone private session-owned resident continuation slot, filled once by a **consuming trusted handoff** of the real Material config, ten streams, original panel and baseline, plus original admission/readback artifacts. That handoff must be constructed at a trusted deployment boundary from these actual capabilities; it is not a caller-supplied trait object, callback or metadata setter.
2. The session verifies its original registered daemon identity and held pidfd and validates the A source binding/profile. It constructs the actual concrete Candidate stage owner with `from_original_streams` or `recover_original_streams` as selected by its privately retained authorization origin. It calls the same service's register/recover method and then consumes that registration through `into_candidate_runtime`.
3. Register a real connected V3 endpoint and serve `RootResidentLearningHandleV3::serve_original_stream` using the original consumer pidfd/identity and unchanged timeout/lifetime. The sender transfers the live endpoint and bounded sealed profile for the same operation. No response uploads a snapshot or supplies signatures to be signed.
4. The daemon consumes it through `AgentdRootResidentLearningClientV3::{from_original_root_stream,recover_original_root_stream}`, then the already implemented enrollment/delivery path performs actual A/outbox reconciliation. The preflight cannot claim A's outbox. Only after successful preflight and durable claim is fresh Admit permitted.

The code placement is `authority_host_session.rs` plus a new private resident-session module, the corresponding trusted producer/handoff module, a narrow `production_launcher.rs` receiver branch and `config_resident_learning.rs`/`resident_learning_delivery.rs` composition. The core resident coordinator, verifier and concrete stage owner APIs remain the existing ones. Every new consuming method must have this actual serving or startup caller and an exact CALLERS boundary; an unused `with_*` API is not this slice.

### Slice C — Root lifetime and cold reopen

The old `authority_host_learning_session::serve_optional` is tied to A's original session and owner pidfd. It shuts down its learning socket when that scope ends. **It cannot be reused unchanged for resident work that must survive A exit.**

The new supervisor must retain the same service inside the original Root process and separate A-lane completion from Root-resident cancellation. A exit closes A's channels; it must not cancel already admitted resident work. Root cancellation, original grants/leases, original channel deadlines and the runtime's own uncertainty fences still stop work. This is a lifecycle implementation change, not permission to extend any lease or session lifetime.

On cold reopen, consume the same original protected record under the separate readback authorization and recovered original role channels. Missing/partial/foreign records fail. `Prepared`, vacant, missing, or unknown-completion observations never become Fresh. No same-operation execute retry follows a lost ACK. Cold readback must preserve complete original D/T/B/S/C signatures and final Source/Cell/CURRENT observations; only an actual terminal authenticated six-cut result can retire the original outbox.

## 6. What truly requires deployment input

The implementation can create bounded queues, exact-purpose framing, consuming wrappers, process-lifetime supervision and readback validation. It can load actual model bytes supplied by the authorized task host, validate existing signed records, and pass existing original capabilities to existing consumers.

It cannot supply these missing facts itself:

- An authorized original A publication and its matching original FinalUse grant/consumed witness.
- Independent role-host processes, their original enrolled signing custody and real connected streams/pidfds addressed to this final Root process.
- Genuine A Decision and Outcome signatures, the independent measured Outcome support, and a signed frozen Dataset plan covering that same Source.
- A primary/retention evaluator deployment registered for the same candidate profile.
- Pre-existing provisioned resident admission/readback policies and original exact leases for the required subject, operation and scope.

Those are inputs from the original owner/deployment, not new command-line fields we should invent. Their absence prevents execution/qualification, but it does not prevent implementation and source/native mechanism testing of Slices A–C against explicitly provisioned original owners. The mechanism tests must label their fixture provisioning and same-process transport exceptions; they do not replace the ordinary deployment run.

## 7. Executable verification path without changing budgets

| Stage | Real mechanism that must run | Negative proof | Qualification meaning |
|---|---|---|---|
| Current narrow prerefusal | Actual Root protected registration, concrete role origins, actual Material handlers | Every mismatch rejected before a queue exists; zero original CAS replacement, issuance-sequence delta and role frames | Source/Root mechanism only |
| A capability slice | Actual initial publication/FinalUse, real Source/Cell and ordinary authenticated RunStart | Missing/wrong Current, revoked Artifact or FinalUse, wrong original profile or peer | First ordinary A setup only after genuine non-Root launcher run |
| Late Root producer | Same prepared service, final Root-targeted role transports, actual V3 serving and enrollment | Wrong UID/incarnation/pidfd, missing one stream, expired original end, duplicated handoff, old V1/V2 schema | Does not yet prove complete NoUpdate |
| Evaluated retention | Same actual A → E/D/T → independent B → Version/S/C through original channels | Withdraw D/T/B/S/Source/CURRENT, lose Execute ACK, cancel at the real send boundary, fifth Trainer connection | Complete ordinary NoUpdate only after all original evidence exists |
| Cold daemon plus Root | Stop both actual processes; reopen existing owners using genuine readback authorization and same-operation records | No reconstruction, re-signing, lease renewal or re-execution; exact original six-cut evidence | Cold qualification only after full process restart succeeds |

Use the existing five-crate native scope, original per-case stack/time limits and Root protected-bind harness. New parents must be added by exact function name to the existing Root case list. Run the unchanged source verifier over the actual full tree and the unchanged full caller proof. A scoped Python source PASS, a test-only fixture, a partial stack of library APIs or an exit-zero formatter cannot increase any of the four ordinary qualification counts.

## 8. Independent origin prerefusal already prepared

`profile-resident-origin-57b-v1` implements a narrow necessary correction: `runtime::compose` compares the registration's private `readonly()` origin with the concrete stage bundle's private origin before creating any runtime queue. The getters accept no caller flag and cannot install a gate or promote recovery. The original `install_fresh_resident_gate` checks remain unchanged after the actual fresh CAS.

Its native test source covers NoUpdate/Candidate × Fresh/Fresh, Fresh/Recovered, Recovered/Fresh and Recovered/Recovered. It retains the actual protected record inode to prevent reuse, compares complete bytes, reads the actual issuer's durable sequence without issuing sentinel grants, and counts original Material handler frames plus the explicitly marked zero-frame Trainer probe. The wrong pairs must fail with the exact origin error; the correct pairs retain their private read-only mode. The runtime is not dispatched by this test.

At this document's freeze point, the **four local source suites have actually passed 30 tests** on their explicitly recorded physical overlay, with all 296 input identities unchanged. The original failed locator attempt is retained. The isolated actual Rust 1.96 formatter has completed with return code 0; its manifest and all seven postimages were independently read back and verified. Only the new test module changed formatting. Native execution of the new case remains pending Root's native queue; the two timed-out start acknowledgements are preserved separately and are not treated as observed PTY exits. This correction is not ordinary main assembly and all ordinary qualification values remain **0**.
