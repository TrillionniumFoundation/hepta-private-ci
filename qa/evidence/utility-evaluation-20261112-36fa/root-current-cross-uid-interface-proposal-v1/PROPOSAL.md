# Root CURRENT custody across the ordinary process boundary

## Status and exact decision

This is a source-grounded interface proposal, not an implemented transport or a working three-UID path. The original source is `cc57c7198db6293ccca562253c42fffbe2a04633`; the prepared Version/S/C references are the immutable Root86 overlay `3f7d40d4933669da33d2aef3491efb431c5771ae`. `SOURCE_PINS.json` binds the complete files used here. No source, ref, native control, formatter or test is changed by this proposal.

Keep the concrete `NeuronGenerationCurrentOwnerV1`, its original Root directory, and the complete *generation* publication coordinator in the trusted Root process. Keep the actual D/T/E readback owners and their existing context checks in the Version host; do not add another Trainer connection to work around this split. Do not expose a generic store/CAS callback to the non-Root Version host. A caller-proposed head or a fresh copy of a CURRENT file would omit the exact journal, Artifact and FinalUse checks that currently surround each CAS.

This alone is insufficient to deploy the existing 60001 A/Material/Version/S/C placement. The original published task and its completion are sealed same-process values. A production solution must also supply a concrete original task/live-guard custody bridge, or deliberately move the corresponding original task owner into the trusted host and provide an equally narrow actual execution service. Neither bridge exists in the reviewed source. No callback, fabricated owner or unavailable stub is proposed as a substitute.

## Operations that must stay with original Root custody

| Operation | Exact existing entry and retained inputs | Required observation |
|---|---|---|
| Open or create CURRENT | `NeuronGenerationCurrentOwnerV1::{open,initialize,prepare_initial}` with the actual `Arc<RootAuthorityDirectory>` | Existing Root-owned ancestor/final-directory policy and concrete CurrentStore. Absence is not an invitation to create a replacement history. |
| Prepare the first A task | `prepare_agentd_generation_initial_v1` | Original selected Artifact and complete target config, actual empty target file and empty independent witness; Root Preparing record followed by actual header/genesis and Current readback. |
| Publish the first A task | `PreparedAgentdGenerationInitialV1::publish` → `publish_initial` | Original independently signed FinalUse binding; claim and dispatch witness; actual genesis and selected Artifact revalidation around the protected CAS. |
| Prepare retained same-model C | `prepare_agentd_generation_cold_same_model_task_v1` → `prepare_same_model_task`, currently called inside `prepare_original_circuit_evaluated_retention_v1` | Keep the outer actual D/T/E checks in their original Version context. Root's generation operation receives the exact original completed A/custody and selected manifest, real stopped/drained predecessor file plus independent witness, and actual empty C target. Keep the predecessor lock through publication. |
| Publish C | `PreparedAgentdGenerationUpdateV1::publish` → `NeuronGenerationCurrentOwnerV1::publish` | Original independent FinalUse authority and grant, selected Artifact current, exact predecessor/target journals, original witness and exact operation. Only the original bounded dispatch changes CURRENT. |
| Live authority check | `LiveGenerationCurrent::check_current` | CURRENT before, actual selected Artifact and retained FinalUse verification, then CURRENT again. A cached successful sample cannot serve later requests. |
| Recover the same original operation | `recover_{initial_}operation`, `read_{initial_}operation`, and `recover_agentd_generation_{initial,update}_v1` | Same original operation and intent, actual published record and retained witness/grant, same nonempty journal, original Artifact/FinalUse checks, then a second original Current read. Prepared/absent remains unavailable or uncertain; no new grant or redispatch. |

The actual publication input type is `OriginalCircuitRetainedPublicationInputsV1<Old, New>`. Its `current` field is `Arc<NeuronGenerationCurrentOwnerV1>`, and the Version host also retains that concrete owner for later operation readback. The type is not a snapshot parameter or an interchangeable store adapter. Current prepare performs `store.replace(expected, next)` and reads it back; publish performs its CAS inside the original FinalUse claim/dispatch boundary.

The Root issuer and FinalUse consumer are distinct. An ordinary consumer may use its own euid-private nonce store together with an explicitly trusted issuer/clock/frontier. The UID-0 Host issuer keeps its own Root lease and signing custody. No solution here requires UID 0 to reopen a UID-60001 consumer's nonce directory as its own, and doing so is not a way to obtain the original Current owner.

## Existing authenticated inputs and what they do not provide

| Input | Existing legitimate acquisition | Limit at this boundary |
|---|---|---|
| Original A task request and model | Parent-held complete ObjectiveStart contract, exact signed ingress, original model files and selected manifest | An ingress or run-status response does not provide `PublishedCircuitFeatureCompletionV1`. |
| A Decision, Outcome and freeze | Original complete retained signatures, original full ledger, original freeze payload; checked against parent-held full trust by Pending Material admission | The completed-task digest stays a pending claim until the original Material E/D handlers verify the live Source. No Source owner is reconstructed. |
| Material E and D | Original Experience Execute/readback then Dataset Execute/readback; original handlers re-read the actual Source, ledger and freeze | A pure readback cannot create fresh D. Pending cannot skip to Training or mint Root authorization. |
| Original T and Candidate | Original Bootstrap/command/readback endpoints, bound to the actual D; Candidate material comes from the same original T | Data or a T digest cannot replace the live typed connection or original full signature. |
| Independent B and E | Existing independent Panel members and original Trainer evidence client, followed by the original E host | The four objective fields can be passed as a test-only borrowed contract, but A input/history and actual D/T remain separately authenticated. |
| Original Artifact selection | `AgentdSelectedGenerationV1::load` from actual Artifact owner, independent selection verifier/signature and original immutable selected files | A signed selection digest alone does not supply original current Artifact custody. |
| Original FinalUse | Existing `AgentdUnixFinalUseGrantProvider::from_root_stream` and purpose-fixed retained-version provider | This authorizes the exact original effect only. It neither transfers CURRENT nor turns a fixture FileCas into Root custody. |
| Original A retirement | `PublishedCircuitFeatureTaskV1::drain_completed_task` on the same task and Cell, actual Source readback and identity | Requires `Arc::ptr_eq(task, cell.task)`, original Source/Cell equality, durable drain and repeated current checks. Its opaque completion cannot be made from a reported digest. |

The Material-only split `a72dc791ed6026ae49b0500a52dc295f9b3622ad` now makes A/Material available before any Trainer or test transport is constructed. It enables a separate public Material-to-Trainer transport experiment. It still deliberately uses the existing test Current fixture and is not a production Current solution.

## Exact missing production interfaces

### 1. Original published-task/live-authority custody across processes

`PublishedCircuitFeatureTaskV1` contains a private `PublishedTask` with the actual original journal and an `Arc<LiveGenerationCurrent>`. Its crate-private `from_initial` and `from_update` are reached from original Ready publication owners; the field is not merely `Arc<dyn CellGenerationCurrentV1>`. Its Cell and Feature control paths recheck current before/after actual work.

A non-Root A/C process therefore needs an original purpose-bound task capability that continues to consult that same live Root authority. A reviewable bridge must bind the exact Root peer, consumer UID/PID/boot/start/pidfd, full original publication and task, selected manifest, original operation and absolute end. Its read path must invoke the actual Root `LiveGenerationCurrent` checks; it cannot reply from a copied publication or frontier. It must consume actual custody once and preserve old local constructors. Returning a generic callback that says current would discard the original type restriction.

There is no such producer/receiver pair in the reviewed code. Adding a remote `check_current` client alone does not make `PublishedCircuitFeatureTaskV1::from_parts` accept it, and returning the private original journal/Root owner through a getter would create a different authority surface. The first implementation unit must explicitly solve that type and custody edge; it cannot be hidden in a serde adapter.

### 2. Same original A retirement into the Root publication coordinator

The complete predecessor is obtained by the actual task's `drain_completed_task`, not by the child supplying `{drained:true}` or a checkpoint. A transport must preserve the original journal/witness ownership and exact A completion provenance. The trusted receiving side must verify the actual original objects and their association before entering `OriginalCircuitRetainedPublicationInputsV1`.

`prepare_agentd_generation_cold_same_model_task_v1` is the appropriate existing cold entry after A stops: it opens the same nonempty predecessor with the concrete Root floor, verifies real durable drain, and retains that lock through CAS. It does not itself authenticate an arbitrary remotely encoded `PublishedCircuitFeatureCompletionV1`; that opaque input remains a separate missing handoff. Do not reopen the live A Source or ledger writer to simulate it.

### 3. Return of the actually published C into the original daemon path

The Root coordinator must retain its actual prepared/Ready state through the result. The consumer must receive only the exact published C capability; unknown acknowledgement retains the original operation for readback, not a new prepare/publish request. `OriginalCircuitRetainedVersionHostV1` must still install and revalidate the same C and actual T/E cut before its original `run_original_c` consumes the config once and enters `crate::run`.

The live C task capability must enforce the same Root Current/Artifact/FinalUse checks throughout daemon and S/C reads. The previous Admission's test `RuntimeFixture.state` is not the new daemon state. A version-publication response cannot be treated as a successful C ObjectiveStart; the original Agentd control client and exact signed C ingress still perform that action.

## Proposed implementation boundary for Root review

Use an operation-specific Root generation-publication service which owns the *whole* existing initial or generation-update preparation, original authorities, original selected Artifact and actual journal custody. Its outward interface should be a non-Clone one-operation session plus read-only access to the same retained operation. It must not accept arbitrary expected/replacement CurrentHead values, generic storage callbacks, caller-selected purpose or re-created journal witnesses.

The initial insertion is the trusted host immediately before `prepare_agentd_generation_initial_v1`. For retained publication it is the existing cold-generation operation inside `prepare_original_circuit_evaluated_retention_v1`, after the original context's real D/T/E checks and before/after its existing live rechecks. Those evidence clients stay in the original Version host with the same slot, counter and deadline, so later V/S/C sharing still refers to the same two Arcs. The service must not add a fifth T connection or reproduce a readback from cached signatures.

The original generation implementations remain responsible for actual journal validation, prepare/CAS, FinalUse claim/dispatch and uncertain readback. A new, explicitly named remote-Root constructor and sealed private operation state would be needed alongside the old by-value constructors. It would adapt the current concrete `PreparedAgentdGenerationUpdateV1`, operation-control and installed-live types; it must not generalize the old public inputs into externally implemented traits. Root-owned Artifact and retained-FinalUse current checks must also stay bound to that same concrete service. A local clone of the Artifact history is no substitute.

The associated task/live-guard and retirement handoffs must be concrete sealed producer/receiver APIs anchored to actual original owners. They require their own exact source review; their names, framing and implementation are not established by this document. Moving the whole Version context and T/E clients to Root instead is not an assumed shortcut: it would break the present same-process V/S/C sharing and require a separately reviewed role topology.

This design preserves the proposed non-Root role separation without handing the Root directory to UID 60001. Moving Version, S, C and the original task into UID 0 instead is a larger topology change: the existing resident stream interface expects actual authenticated role endpoints and must not accept same-UID Root loopback by relaxing `f42`. Neither option is already implemented. The current three-child role table is a plan, not an observed placement.

All new transport work must preserve the existing role/purpose separation, nonce/one-consumption rules, original deadlines, 4-permit and aggregate-request limits, no-queue failure behavior and retained Unknown semantics. A new control message cannot enlarge the 64-KiB aggregate report budget or modify the original checkpoint/right protocol as a side effect. Precise frame and operation limits must be fixed in the implementation proposal from the actual original budget; this document does not invent additional allowances.

## Work that can proceed without inventing custody

1. Complete the public A/Material-to-Trainer fixture binding using the now-separated Material object and the original public endpoints. Label its test Current dependency explicitly.
2. Separate B's borrowed objective contract from the opaque Source publication, while the actual D/T and Material bindings still supply its A provenance. Preserve the existing wrapper and all old assertions.
3. Keep Pending limited to complete report/contract authentication, original Root profile binding and consumption of a pre-existing genuine Registration. Exercise rejection and cleanup with original mechanism inputs, not a new grant factory.
4. Specify and review the three concrete Current/task/retirement interfaces above before implementing a production cross-process publication adapter. Missing original input remains unavailable or Unknown.
5. After an actual implementation is frozen, compose it with the existing S/C local capabilities, registration and exact-source gates. No current fixture, code compilation or hypothetical topology can be reported as a completed real A/B/C/Root task.

The remaining gap is substantive production interface work. The overall chain is not merely awaiting formatter or test execution.
