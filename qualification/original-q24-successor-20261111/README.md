# Original Root Q24 successor installation

Status: source prepared against `5daade9e4ce374ac169702d6b59490149ccefd34`; this package contains no Rust compilation, test-run or deployed qualification result. The original baseline's results do not qualify these changes.

This source defines a protected internal, conditional Pending Circuit profile. **The current ordinary A production flow cannot supply all of its constructor prerequisites, so this slice is not yet a reachable A-to-C startup path.** Given an already legitimate original retained-A learning assembly and a fresh unconfigured Root launch, the internal API can install the closed profile before running. Its task build, submission and readback fail immediately until the original required worker has completed the actual Root publication and opened the actual Q24 task channel. No request is queued across installation. The worker is bound to the same actual aggregate, frozen request/owners/scope, full consumer identity and live Root session. A public PublishedTask, receipt, descriptor, callback or caller-supplied provider cannot fill it.

## First production reachability failure

The new entry requires both a fresh original Root/Q24 Launch and the actual retained A source. The current implementation cannot obtain them in one legal ordinary lifecycle:

- While the original A daemon is still Running, its Circuit Config has already been consumed and its task/provider slots are occupied. There is no same-Running phase-transition API or post-A scoped Learning/Model enrollment on the live original Root service. Pending cannot replace that task or use a placeholder learning scope.
- A legitimate successor spawn requires the original process to exit. The Supervisor observes actual `ProcessState::Exited`, finalizes that exit, removes its lease and only then starts the next generation. Root checkpoint adoption also requires a truly retired predecessor lifetime and rejects the same old/new peer. Dropping a service or waiting for an old lease to expire is insufficient.
- The retained A source is a private capability held by the original process's `Arc` graph. Its current API can preserve read access after releasing old task writers in that process, but cannot reconstruct or transfer that historical authority after the process exits. The late-writer Launch adapter does not supply this missing capability.

A different agent, public PublishedTask, copied receipt or descriptor cannot satisfy the original source/request/scope and same-session checks. We found no other ordinary production constructor path that supplies the required pair. A real historical-source reconstitution protocol across incarnations, or a real same-Running phase transition and scoped enrollment, is still missing. Neither is implemented by this slice.

The proposed two-phase positive component is therefore stopped at this actual boundary. Mocking process exit, manually changing Starting/Ready, copying A's trace into C or injecting an owner would conceal the gap. The existing Root parents and actual A/Trainer tests remain useful independent components, but are not a positive Pending-successor chain.

The exact source pins and method names are retained in `SOURCE_GAP.json`.

## Conditional internal sequence

The following describes the implemented guarded protocol **if its original capabilities already exist**. It is not an instruction for completing the missing ordinary startup transition.

1. Use the original Root/retained-source assembly to obtain the actual Launch and Config. Call `AgentdProductionLaunch::prepare_original_q24_successor(config, capacity)` once. Keep the returned opaque handoff; start the original launch/runtime normally. AppServer, Running, AuthBus and learning admission checks are unchanged.
2. Read `handoff.decision_snapshot().await`. This is the exact prefix already checkpointed or restored and authenticated by the original learning loop. It is signing context, not publication authority. The loop waits only for its registered successor, without holding the original aggregate lane or checkpoint transport and without extending the original absolute request deadline. After the wait it performs the existing current LocalDecision signature check before requesting later owner effects.
3. Construct the existing actual Root publication driver from the same original owners and independent selected Artifact. Call `prepare_original_successor` with the handoff, original predecessor/target and explicit execution resources. The original required Circuit worker performs all existing model, source, Artifact, scope and predecessor checks, plus current actual daemon admission and the original slot's live Installing state, immediately before the original CURRENT preparation.
4. Request the exact FinalUse grant from the original issuer using the returned binding. Pass that signed grant to `OriginalQ24PreparedSuccessorV1::publish`. The same supervised worker revalidates original sources and current admission, calls the original claim/dispatch/publication path, and opens the original Q24 task channel. Only then does it publish the actual owner to the Pending slot.
5. Use `original_installed_successor_ingress()` and the original signed ObjectiveStart. Installation is not C execution. Actual source/Cell/CURRENT readback is still required. Once actual C is observed and original Selection/NextUse owners are installed in the aggregate, a lane-exit notification releases the original learning loop; it still obtains and authenticates the real receipts.

## Cancellation and uncertain completion

The handoff, queued installation, original grant wait and original worker share one opaque slot. Drop, cancellation, deadline, wrong binding or installation failure closes it permanently. Pending calls are never buffered for a later Ready phase. Cancellation is checked again inside the original aggregate lane immediately before a new effect. An already-started original effect is joined, not aborted. Installation and original channel work remain visible to the daemon's existing drain accounting after close.

Errors after a preparation may have occurred retain their original cause and carry `OriginalQ24SuccessorPreparedUncertain`. This does not authorize another publication, fresh nonce or repeat claim. The wording is intentionally "may already be prepared": transport cancellation alone does not prove that preparation succeeded.

This slice supports one fresh installation in the same live original Root session. It does not rearm a closed slot, reconstruct retained capabilities from bytes, or install an old task into a new spawn. The original durable operation must be handled by a separately valid original readback procedure; generic `recover_feature` is not an automatic restart recipe.

## Test scope and remaining connections

`TEST_ROSTER.json` lists eight unexecuted component methods: six finite-state/notification negatives and two using actual original signed-task/admission fixtures. Synthetic checkpoint data is confined to state tests. These tests do not prove actual Root nonce/CURRENT behavior or a positive successor installation.

Existing Root parents 16 and 17 provide real cross-UID publication infrastructure, but lack the original HQ24T002/Training aggregate and registered retained-A capability required here. A valid positive component must first resolve the actual lifecycle/capability handoff documented above. The earlier same-child two-phase recipe is not a legal replacement for process retirement. No positive successor component has been assembled or executed, and no fake Ready state or synthetic completed checkpoint is accepted as its substitute.

The installed invocation currently retains the original nonlearning DurableSource behavior. Actual C source/Cell can be read and captured as Dataset input, but automatic C-to-next-A learning Ready additionally requires the real C Generator/Ledger profile and an independently observed Terminal. No Outcome or new learning scope is derived from task success. The old B matched-budget/full-cost contract is unchanged.

Ordinary business loop, adoption, independent B/C, rollback and actual daemon/Root cold-restart qualification counts remain zero.
