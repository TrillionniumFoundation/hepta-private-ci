# Minimal real CLI / host integration proposal

**Status: design only, against the frozen sources. No product edit, h/native run, ref change or qualification is included.**

The next useful cut must contain a real host consumer and real material loaders in the existing two executables. Calling the two new public Startup/Root methods alone would leave the present gap intact. The minimum complete delivery has four parts: explicit entry selection; concrete original-material orchestration; a real B runner/provider integration; and a terminal protocol that proves actual phase-owner join. Missing business data, independently enrolled signatures and holdout observations remain external prerequisites.

This proposal builds on the exact inventory README `60e0b3a3c4b3b57c4eff2140422569be57643172` and source index `97eb5cf961241f52c77fd9474c4e41b7520996d1`. S01–S26 refer to that index. P01–P18 below refer to the additional exact sources in `INTEGRATION_PLAN_INDEX.json`. All statements about a new module, branch, terminal message or state are proposed work, not existing capability.

## 1. Reusable code versus materials nobody can infer

| Obligation | Existing implementation that can be used | Production work that can be implemented autonomously | Real deployment input still required |
|---|---|---|---|
| Starting, peer and writer | Original Supervisor/Starting comparison, late-writer parser, three-right receive and five lanes; frozen Root host sends original rights. | Wire an explicit branch in existing main and Root CLI to the concrete phase deployment driver; preserve old branch exactly. | Actual dedicated UID/GID and process incarnation, registered writer, held pidfds, inherited Control/AppServer/Primary and phase datagrams. |
| Initial Root files | `RootGenerationInitialDeploymentFilesV1::open_original_initial_deployment` pins actual Root metadata, directories, target files and original deployment description. | Reuse its private original-input loading/checking body with the same-phase capability. | Actual target/model/Artifact trust/selection, Root-private descriptors and witnesses. |
| A | Frozen phase installer performs original Initial prepare/grant/publish, opens actual task channel and Ledger; original Control `ObjectiveStart` admits signed requests. | A deployment driver must actually submit a genuine pre-authorized A request through original Control and consume the actual result. | Genuine source envelope/run/profile bindings, issuer signature and actual application/circuit inputs; separate Observer Outcome/evidence. |
| Learning | Actual Prepared/retained capability, original source/training/local owners and scoped assembly already exist. | Load original files and enrolled keys, retain the event's actual Prepared Arc, feed Learning once, and coordinate Root Scoped registration. | Actual Experience/Dataset/training/local-decision journals/witnesses, original policies/verifier and role-bound keys. |
| Independent B | Freeze-plan, signed evaluate-or-readback, qualification and original receipt/install APIs exist. | A **concrete** production evaluator driver, actual holdout provider adapter and durable evidence sink must run and be supervised; no pre-filled result branch. | Real independent candidate/baseline workloads and costs, held-out data/observations, genuine Evaluator enrollment and authenticated qualification evidence. |
| Artifact/Selection | Original Artifact publisher and Published/Retained `accept_selection` consumers exist. | Load the real publish request, solicit/consume an existing authorized Selector result, open the exact selected files and coordinate Current enrollment. | Actual Artifact lease/owner, qualified candidate or legitimate retain decision, independently signed Artifact selection and its current trust. |
| C and feedback | Original CURRENT/FinalUse publication and mandatory fresh Source + OriginalLedger in this phase. | Submit a genuine C ObjectiveStart and feed its external terminal Outcome after actual execution. | New real C input/run under the original same-actor target contract, original Ledger profile, independent Outcome and signature. |
| Final completion | Current code deliberately does not certify completion or physical join. | Implement the finite terminal ownership/join protocol in §5 and connect its actual result to main/Root CLI. | Actual successful workload and original journals/cuts; a request to finish is not this proof. |

Sources: S01–S26; P01–P10. Existing capability **consumers** in S09 and P10 are not evidence that an ordinary Observer, Selector or B provider already supplies the input. The two slice authors have not identified such a complete ordinary application producer in their bounded inventories.

## 2. Explicit executable branches with owned deployment inputs

### Daemon main

Add one explicit phase selection in the existing `codex-rs/hepta-agentd/src/main.rs` preflight, before ordinary startup or any business file opens. Use a finite concrete startup enum/driver, not a callback that can return an arbitrary owner. The new selector/descriptor names are to be fixed during implementation; do not change the existing literal-only `--root-production-entry late-writer` contract merely to reuse its flag.

The selected branch must:

1. Retain actual phase/scoped datagrams and delegate the existing descriptor-disjointness, Starting, UID/GID and Primary checks to `AgentdOriginalSameActorPhaseStartupV1::from_process_environment`.
2. After descriptor preflight, open a bounded, versioned deployment description as **locator/configuration data**. Construct actual files, witnesses, original owners, verifiers and policies through existing APIs. The description must not deserialize Prepared, a PublishedTask, a live Root context, a grant or an authenticated success receipt.
3. Create the actual bounded phase host channel. Move its worker endpoint into real BusinessInputs; keep the sender and event receiver in a concrete production coordinator that is actually polled and supervised.
4. Run the original phase Startup with the real original arg0/runtime path. The coordinator consumes all events in §4, does actual Control requests/B execution and supplies the corresponding original inputs. No detached background B work and no unobserved event receiver.
5. Keep ordinary mode behavior and errors unchanged; malformed/incomplete phase configuration fails instead of falling back to ordinary or old two-right mode.

The phase currently supports actual Android Primary only. There is no headless Primary, Notes-without-UI or Desktop substitute in this cut. The deployment driver must not make `OriginalAOwnersInstalled` or `OriginalCOwnersInstalled` a replacement for normal readiness/Control admission. [S03–S07, S11, S14, S16, S17; P06, P07]

### Root CLI

Add one explicit same-phase command/branch in the existing `codex-rs/hepta-agentd/src/bin/hepta-authority-host.rs`. It must receive the actual Supervisor-owned daemon pidfd and already registered writer, load the real Root configuration/registration and Initial/Model deployment, perform the original filesystem handoff where required, then call the frozen typed Root host.

The Root command producer must actually consume trusted deployment inputs and the daemon progress bridge in §4. An empty mpsc receiver attached to `serve_original_same_actor_host` would just time out and is not an entry implementation.

**The old deployment wrappers cannot be called unchanged in this phase.** Initial and Current loaders retain useful exact metadata/file/directory checks, but their public wrappers contain the old enrollment capability type and their waits compute `Instant::now() + capability.lifetime`. Reuse only the original-material loading and before/after pin checks through a narrow private extraction. Pass the already retained same-phase capability and original absolute end; do not enter the old `wait_and_register*` timing path. Existing default commands retain their original bodies. [S01, S02, S15; P01–P03]

Root commands use Root-owned enrollment material. A daemon event may carry correlation/profile/selection data but never creates Root rights. The smallest local deployment bridge can reuse the existing bounded Root-private descriptor/trigger mechanism and its file pins. It still needs an actual trusted producer and exact phase/incarnation association. It must not turn a generic JSON command socket into authority, silently reload changed material or reissue a capability after an uncertain ACK.

## 3. Concrete B implementation, not a stored result loader

The private daemon deployment coordinator must retain the event's actual Training readback and use the real native candidate from material. Independent B proceeds with the existing APIs:

1. Produce the real candidate and fixed-expert task observations and drained Cell journals for the registered comparison. Preserve their actual capacity, cumulative training and selective-update declarations and authenticated costs.
2. Call `freeze_cell_learning_evaluation_plan_v1` using the original evaluation profile, actual journals and temporal plans.
3. Call `CellEvaluationRunnerV1::evaluate_or_readback` with the original durable execution store and `OriginalCellEvaluationExecutionOwnerV1`. This method, rather than the unsigned evaluate-only path, preserves signed execution provenance.
4. Use a concrete `FinalHoldoutProviderV1` implementation tied to the selected real data owner. Its manifest must equal the original frozen holdout digest; it may release the actual `TemporalComparisonInputsV1` only after the authoritative fenced holdout owner consumes the plan. Inputs include real training samples/held-out targets, candidate and baseline observations, assignments and snapshot/window IDs. No synthetic arrays or already chosen decision.
5. Use an actual `ProductQualificationEvidenceSinkV1` and current authenticated evidence to `qualify_and_persist`. A nonzero digest is the result of actual durable publication, not a user-entered success token.
6. Build the original EvaluationInputs from the actual completed resources and send one Evaluation command. Do not serialize/rebuild the event's opaque Trainer readback. If evaluation runs in a separate process, a real existing authenticated data/result transfer must be bound to that event and its original files; the local mpsc channel does not provide this transport.

The existing runner implements the checks and consumption ordering, but its provider and sink are interfaces. This bounded source review has not identified a ready-made ordinary implementation that supplies the project's real holdout/Outcome/Selector workload. Implementing a concrete adapter to an actually specified data owner is production work; choosing or inventing the observations, signatures, principals or commercial results is not. If the required real owner/input is absent, this dependency remains blocked. It cannot be replaced by a canned `EvaluationInputs` file that claims B already succeeded. [S19–S26; P04, P05]

B must remain within the original request/phase deadlines. Its real work needs owned cancellation/join custody in the selected production host driver. Bind that driver to the actual original phase context after Root receive; do not reconstruct a new deadline from a CLI duration or run a detached `spawn_blocking` job. Losing the host or timing out closes the phase, keeps the real failure and joins/retains already begun work according to the existing custody rules.

## 4. The event consumer must execute this full sequence

| Actual incoming event | Required real producer action | Original consumer |
|---|---|---|
| `InputsOpened` | Trusted Root producer loads/pins actual Initial enrollment, registers it; bridge returns its real acknowledgement. | Root Initial command/ACK, then daemon `InitialRootEnrolled`. |
| `OriginalAOwnersInstalled` | Through original Control, submit the actual signed A ObjectiveStart only when original readiness allows it; obtain independent terminal business Outcome/evidence. | Existing Control/Objective host, then `CompleteOriginalA`. |
| `OriginalAPrepared` | Retain the actual Prepared Arc locally; transfer its profile data to the trusted Root producer; open original Learning materials. | Root `Scoped`; daemon `Learning` with exact Arc. Existing retained delivery submits the learning request. |
| `OriginalTraining` | Run the real independent B sequence in §3. | One `Evaluation`; later original Evaluation completion and decision. |
| `OriginalDecision` | Use the authenticated actual decision to supply qualified candidate publication or its legitimate retain/defer/no-update input. | `Artifact`; an error is never converted into Retain. |
| `OriginalArtifactAvailable` | Obtain actual authorized Artifact Selector output and original immutable selected files. | `Selection`; it is distinct from Learning Selector evidence. |
| `OriginalSelectionObserved` | Trusted Root producer registers exact Current enrollment; supply actual C target/model/source/execution inputs. | Root `Current`; daemon `PublishOriginalC`. |
| `OriginalCOwnersInstalled` | Submit actual signed ordinary C ObjectiveStart through Control; obtain independent C Outcome/evidence. | `ObserveOriginalC`; actual Ledger must return Complete. |
| `OriginalCOutcomeAccepted` | Begin the finite successful-finish protocol only after actual required obligations are complete. | Proposed completion path in §5; current code keeps serving and does not report success. |

The new ordinary driver, not a person manually sending enum variants, must own this ordering and all in-flight results. External original signers/data owners still supply their real inputs. Source signatures, RunStart, Decision and Outcome are never synthesized by the coordinator. [S02–S10; P06–P10]

## 5. Required final completion and physical-join protocol

### What is actually missing

The Root durable record currently has only Reserved, Claimed and Scoped. The existing control protocol carries only the two A-retirement ACKs. Both client and Root finish that exchange without retaining its stream for C. Root's scoped worker then serves Learning/publication until failure/close. C Outcome acceptance leaves the concrete worker running; cancellation/ending returns Err. [S03, S08; P11–P15]

The outer Circuit task bootstrap starts a real blocking closure and awaits its JoinHandle inside an async required task. Generic RuntimeTasks shutdown may abort an async wrapper after its grace period and accept the cancelled join as normal shutdown for a non-retiring task. That does not prove the blocking closure stopped. The source correctly refuses to turn generic Launch.run Ok into phase completion. [S03; P16–P18]

### Smallest sound new contract to implement

This is a finite closing protocol, not reuse of EOF or a fresh session. A concrete proposed message sequence is: **FinishIntent → FinishAccepted → DaemonOwnersJoined → RootOwnersJoined** on the retained original control channel. Every message names the same phase/claim, exact selected C CURRENT/source/checkpoint and original Outcome/learning cuts. Root validates those data against its held original owners; caller digests are not join proof. FinishAccepted permits only the expected retirement, not new work. DaemonOwnersJoined can be emitted only by the owner of the actual terminal join result. RootOwnersJoined is the single final success ACK after Root's own joins. No new session, grant or writable right is returned.

1. **Retain the original control ownership.** Extend the opaque second-ACK result on both sides to retain the same actual control channel, original peer/pidfd, phase/profile binding and original absolute deadlines through C. Move it through JoinedA/scoped/C ownership; no public constructor from a path, identity JSON or boolean. Do not reconnect at the end or issue new rights/nonce.
2. **One-way finishing admission.** After real C Outcome and original C completion/readback, consume a private finish intent. Under the same queue/admission lock, close C to new builds/submits, keep already admitted exact-C tickets until their actual completion, and enter a non-rearmable finishing state. Root records the exact phase/C cut and finishing intent before treating expected data-lane shutdown as retirement. Normal errors still close the entire original phase and final channel.
3. **Prove local task/learning cleanup.** Use the actual C source, Cell and PublishedTask to obtain the original C durable drain/completion; do not reuse A's saved completion. Await real queued work, blocking observers, concrete Learning/delivery/C workers and retained Work results. Explicitly release any installed slot/source/Cell/Producer/Current references still retained in the route after quiescence. A zero counter alone is insufficient; the existing Closed slot deliberately retains installed resources for accounting. The successful-finish path needs a narrowly owned release capability after actual join, never a public clear/reset.
4. **Keep actual outer blocking-handle custody.** The final join witness must be produced only after the outer phase blocking closure has returned and its captured owners/results have been released. Keep that actual JoinHandle or an equivalent one-shot join owner outside an abortable wrapper so cancellation cannot detach it. Do not publish a witness from inside the closure before its environment is dropped. Generic RuntimeTasks abort remains an error/unknown for this completion path; default runtime semantics need not be loosened.
5. **Join Root owners before its final acknowledgement.** The Root coordinator validates the same original peer and held C/journal cuts, stops and actually joins its original phase/five-lane/scoped workers and releases their owner resources. Retain only a narrowly typed final-response channel and the original record/peer/deadline data. Move this response custody to the outer coordinator before joining the workers; do not make a scoped worker wait for an ACK that requires joining itself.
6. **Commit and send the one terminal result.** A durable finishing/completed state must bind the same original claim, final C/source/learning cuts and both sides' actual join facts. Only then send the exact final ACK over the retained original channel, still within the original deadlines and post-write/read time checks. If any effect/ACK is uncertain, preserve the durable state and return uncertainty; no resend/rearm/new attempt. An old closed channel is not revived. Read-only later inspection is not new execution permission.
7. **Connect completion to process lifecycle honestly.** Keep the original daemon shutdown/drain sequencing and actual required-worker joins. Startup may return a successful scoped-completion result only when it has the typed terminal proof and its own real local joins; generic Launch.run Ok alone remains insufficient. Root serving success likewise requires its actual terminal path. An external Supervisor must separately observe real daemon and Root process exits before any OS restart claim. This completion ACK proves only the explicitly joined phase owners, not an operating-system restart.

A safe implementation may need to distinguish monotonic expected finishing from exceptional Gate.close, because the current close operation shuts down every registered channel and Work cleanup intentionally closes first. Any success-only retirement exemption must be private, single-use, tied to the actual original finishing record and original deadline; an error must still close it. This is a real missing protocol cut. It must be independently reviewed with the actual owners and tests before replacing today's explicit failure return. It cannot be reduced to changing that return or adding a `completed: bool`.

## 6. Proposed production footprint and order

These are work targets, not prewritten source or accepted new authority:

| Cut | Existing integration points | Minimal new concrete responsibility |
|---|---|---|
| Entry/materials | `main.rs`, `bin/hepta-authority-host.rs`, frozen `production_launcher_same_actor_phase.rs`, `authority_host_same_actor_q24_host.rs` | Explicit owned deployment branch in each existing executable, strict locator/FD parsing, actual event consumer, no fallback. |
| Root material reuse | `authority_host_initial_deployment.rs`, `authority_host_publication_deployment.rs` and their private input/file helpers | Extract exact material/pin checks; call the same-phase capabilities with the retained deadline. Preserve old wrapper behavior. |
| Daemon business coordinator | Frozen `same_actor_q24_phase.rs`, A/C controllers; original Control/Objective/Ledger APIs | A private concrete deployment host that loads authorized resources, actually consumes events and submits signed objectives, with real supervised lifetime. |
| B driver | `neuron_cell_evaluation.rs`, `neuron_cell_evaluation_owner.rs`, `product_runner.rs` | Concrete deployment provider/sink and execution coordinator over real data; original algorithms, costs, trust and holdout consumption unchanged. |
| Terminal custody | `same_actor_q24_phase_join_client.rs`, Root phase join/worker/record/protocol, C controller, task runtime and RuntimeTasks integration | Retained exact channel; one-way finishing; actual outer handle/resource join; durable terminal state and one final ACK. |
| Closed inventory | Actual new caller paths and parent modules/tests | Add only implemented callers/required IDs/protected order; run original gates on the later integrated source. |

Implement the host driver together with its actual entry and material source; do not land a public-only or permanently blocked shell as “ordinary entry complete.” A legitimate TrainingNoUpdate execution may be an earlier real branch demonstration once real A/materials exist, but does not substitute for positive adoption or B. The positive branch requires the actual B provider/data and independent Selection, and C still has to run through original ingress.

## 7. Explicit external prerequisites and acceptance

Before claiming the ordinary path can execute, identify one actual deployment bundle with:

- Original Supervisor/Root/Primary process and FD custody; real Android application inputs.
- Real A and C signed source requests, selected objective/profile/configuration and finite task resources.
- Actual pre-enrolled Generator/Observer/Evaluator/Selector roles and their authorized key/witness handoffs, not newly invented role IDs or keys.
- Real independent A/C terminal business observations, cost/label profiles and authenticated evidence.
- Actual B candidate/fixed-expert task journals, matched cumulative budgets/capacity, known required costs, holdout data owner/provider, execution store, timing and durable qualification sink.
- Actual Artifact writer lease, original selected files/trust and independent Artifact selection.

The present source inventory does not supply or prove that bundle. No commercial Outcome, holdout target, execution cost or independent principal can be manufactured by adding a CLI.

**Original user acceptance axes remain:** ordinary_complete_chain = 0; positive_adoption_chain = 0; no_update_or_rollback_chain = 0. The earlier inventory's ordinary-A / independent-B / independent-C table is an additional observation table (also 0/0/0), not a replacement for these original axes. True daemon + Root OS restart remains unaccepted. Current same-actor C remains different task data under the original same-principal contract; it is not independent-consumer adoption.

No existing or in-flight native result is reassigned to this proposed later source. The later complete candidate must run its own original gate set and actual configured ordinary workload; component tests and static caller inventories do not fill these business/deployment facts.
