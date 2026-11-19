# Ordinary A → retained learning → Pending C: a remaining production reachability gap

## Fixed scope and result

This is a source audit of commit `19894714403a97fcd58ca8c592e75761de95687c`, tree `8c64ab5145f279cafec363130d2a917075800e56`, whose parent is `2125da36a0e49a19b725c28bb150900f20caac7b`. The commit and parent/tree were read from the Git object API. Thirty-one exact source files were fetched at that commit and their bytes, Git blob IDs and SHA256 values are recorded in RESULT.json.

**The proposed same-process two-phase positive component cannot be assembled through the current ordinary production lifecycle.** It requires both a retained A capability that stays in the old process's memory and a new Supervisor Starting admission that follows the old process's actual retirement. The original Supervisor and Root checkpoint owners do not accept merely stopping a runtime, dropping a lock, expiring a lease, or relabeling a live process as retirement.

The new Pending successor slice remains a conditional capability: if an actual original Launch, matching assembled learning owners, original retained A and the same live Root session already exist together, it provides the controlled path toward publication and installation. The current source does not provide the missing ordinary path that supplies that combination after the earlier A runtime. This is a concrete lifecycle/custody code gap. It is not resolved by adding deployment keys or by writing an unexecuted positive fixture.

This finding does not redefine legal NoUpdate, RetainParent or signed DeferCandidate as failure, and it does not turn missing custody into a NoUpdate result. The original business decision branches remain distinct; the missing ordinary source/admission join cannot be supplied by choosing another outcome label.

No native build, test, process launch, Root operation, service stop, registry mutation, ref change, fake process retirement or new protocol implementation was performed for this audit. Ordinary complete-chain, positive-adoption, NoUpdate/rollback, independent-consumer and physical daemon/Root restart counts remain zero.

## 1. What the Pending entry actually requires

[AgentdProductionLaunch::prepare_original_q24_successor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/production_q24_successor.rs#L8) operates on an existing original Launch and Config. It requires learning assembly and rejects a still-unconsumed Model factory or initial-publication purpose. It captures the actual Root session and asks the Config to install its bounded waiting service.

[AgentdConfig::with_original_pending_successor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/config_q24_successor.rs#L9) requires the Circuit execution profile, no existing Circuit task profile and an already present learning bootstrap. It does not create those capabilities. [prepare_original_successor_context](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/learning_iteration_successor.rs#L39) then requires all of the following to agree:

- Concrete original Q24 stage owners and their actual Prepared scope.
- A previously registered retained A source.
- The original Root delivery registry containing exactly the Prepared request.
- The original owner set, scope, source identity and live Root session.
- A fresh one-shot successor slot, with no previously installed generation.

Those are real predicates. Removing them to make a fixture constructible would change the product authority model. The negative slot/route tests in the slice do not establish a positive ordinary input supplier.

## 2. The retained A value is an in-memory custody join

[OriginalCellQ24RetainedLearningSourceV1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/cell_q24_retained_learning_source.rs#L24) has private fields for the actual producer, Prepared capability, captured source/decision/outcome, original AutomationStore, an open database file and a permanent fence. [retained_learning_source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/cell_q24_retained_learning_source.rs#L50) constructs it only from the actual producer after accepted Terminal output and witnessed ledger/trace agreement. Its read side intentionally shares original source, journal and Ledger capability while releasing active Cell/generation writer custody.

The retained registration is also a real join. [with_retained_q24_source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/learning_iteration_retained_source.rs#L7) requires the current original Root bootstrap, actual Q24 owners, exact Prepared request/scope and original delivery registry. It accepts the opaque retained value; there is no ordinary JSON or raw receipt constructor.

The existing [retained-source startup adapter](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/production_q24_retained_learning.rs#L50) is useful when its caller already owns that value and a legitimate new startup. It does not make the value survive an actual process exit. The current producer journal binding also includes [the original spawn_generation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/cell_q24_task_ledger_binding.rs#L91). Reopening a journal under the new identity is not the same operation as authorizing read-only use of its historical identity.

This conclusion does not say that completed experience expires whenever CURRENT changes. The actual Dataset task reader explicitly permits historical execution and advanced CURRENT when its original publication and current Dataset authorization remain valid. The missing part is obtaining a lawful new-incarnation source capability after the process that held it has ended.

## 3. Actual Supervisor restart ends the old process

The original path is concrete:

| Original operation | Actual prerequisite or effect |
| --- | --- |
| [restart_slot](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-supervisor/src/control.rs#L118) | Queues the original restart claim and drains/stops the retained active runtime. It does not allocate a new incarnation inside that live runtime. |
| [tick_runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-supervisor/src/tick.rs#L156) | Calls exit finalization only when the real process driver reports `ProcessState::Exited`. A Running observation, even when drained, is not that branch. |
| [finalize_exit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-supervisor/src/tick.rs#L269) | Removes the exact original ProcessLease and transitions a drained/failed lifetime to Stopped. |
| [start_release_slot](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-supervisor/src/recovery.rs#L101) | Requires no active runtime, no unresolved process lease and Stopped/Failed. It then performs the actual Registry Starting CAS and invokes the real driver's spawn. |
| [AgentdConfig loading](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/config.rs#L227) | Requires the actual Registry to be Starting at the exact supplied spawn generation, with the original layout/workspace. |

A test Driver that returns Exited while the retained A process continues running would manufacture the very fact that these owners require. Directly rewriting Registry lifecycle or manually marking Ready would bypass the reviewed path. Neither was implemented.

## 4. Root independently rejects a still-live predecessor

Even bypassing the Supervisor in a test would not satisfy the independent original Root recovery predicate.

[RetiredCheckpointPublisher::observe](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/authority_host_checkpoint_publisher.rs#L32) is Root-only and same-boot. It accepts the former lifetime only after a real `pidfd_open` ESRCH, an actual pidfd exit observation, or an independently observed different start time at that numeric PID. The same live PID/start-time returns Conflict. UID changes, unrelated read errors and absent pidfd support are not retirement evidence. A retained publisher handle similarly requires its actual pidfd to report exit.

[validate_adoption](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/authority_host_checkpoint_adoption.rs#L190) additionally rejects equal old and new peer lifetimes, requires the predecessor to be retired and the successor alive, preserves the original owner, and enforces the original writer/publisher generation ordering. [PreparedMaterialRecovery::observe](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/authority_host_checkpoint_material_recovery.rs#L47) obtains those capabilities from the real protected CURRENT and kernel observations; install/adopt further enforce the old-expired/new-live writer window.

The existing native recovery caller illustrates the intended shape: it registers [the actual separate successor process and its start ticks](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/native_g2_entry/recovery_registration.rs#L56) along with the Supervisor generation. It does not keep the old publisher alive and reuse its memory as the new owner.

Therefore the proposed same UID60001 child retaining A while becoming its own new Starting publisher fails two independent original boundaries. Keeping the UID constant does not make the process lifetime constant or supply an authorization to reuse the old one.

## 5. Recovery APIs that already exist

The gap must not be summarized as “there is no recovery implementation.”

| Existing lower-level API | Real inputs and scope | What it does not supply |
| --- | --- | --- |
| [DurableCircuitTaskSourceV1::recover](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/circuit_task_source.rs#L195) | Actual original file, witness, identity, fence, registry and source bytes; it can acknowledge one fsynced suffix. | A new input, completed Pending record, new computation or a new-incarnation retained-A authority. This is an original writer-owning recovery, not a deserialized read-only capability. |
| [CellQ24DatasetTaskV1::capture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/cell_q24_dataset_materializer.rs#L150) | Original source read capability and actual committed Cell decision, checked before and after capture. | A constructor from arbitrary projected vectors, old receipt JSON or a supplied run ID alone. |
| [CellQ24DatasetFreezePreparationV1::recover](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/cell_q24_dataset_preparation.rs#L62) | Actual original Ledger, already constructed task capabilities and retained snapshot; validates against the current witness. | Recovery of the task/source capability itself or permission to re-sign an advanced historical freeze. |
| [PreparedHostAuthoritySession::recover_with_physical_material](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/authority_host_session_material.rs#L118) | Actual protected CURRENT, independently retained image, registered successor and real old-process retirement. | A same-live-child restart or custody transfer of the private learning/source Arcs. |
| [AgentdConfig::from_root_writer_handoff](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/config_root_late_writer.rs#L13) | Original sealed/live Root inputs and the real three-right Root0600 writer descriptor, after legitimate Starting. | A new Starting transition, old-process retirement, or reconstructed original A. |

Root session exit also has explicit semantics: [AgentdRootAuthoritySession::drop](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/19894714403a97fcd58ca8c592e75761de95687c/codex-rs/hepta-agentd/src/root_authority_session.rs#L347) fences its original cache before releasing its consumer references. Retaining another Arc or pidfd does not revive that session. CURRENT and FinalUse observations establish their original durable state; they are not a new execution grant or permission to reuse a consumed nonce.

## 6. What remains unimplemented

Two different product designs could address the missing join. Neither has been implemented or selected by this audit.

### A. Explicit historical-source custody transition to a new incarnation

A versioned original-owner operation could authorize a new, read-only source observer after real predecessor retirement. It would need to preserve the old operation, source identity, signatures, Ledger records, task history, publication and witness facts as historical facts, while separately binding the exact actual new Starting identity and current Root authority. It must not re-open a retired task writer just to manufacture a reader, deserialize an old in-memory cap, rewrite old signatures or label a cached descriptor as an original owner.

The current Source/producer/Dataset recovery constructors are inputs to such a design; they are not already that transition. Its recovery and partial-commit semantics, revocation rules and monotonic independent evidence must be specified before a safe implementation can claim it.

### B. A real phase transition inside one continuing Running incarnation

An alternative would deliberately avoid a new Starting admission. The original running worker and Root service would have to support an explicit, scoped transition from completed A to later Dataset-derived learning/Model enrollment, retaining the actual A source in that same lifetime. The current configuration and Root learning assembly are startup operations; there is no existing product transition that hot-installs that complete authority set into the already Running A worker.

Such a transition must preserve in-flight-task/drain ordering, original source and Root ownership, one-shot enrollment and cancellation fences. Reusing the word “same session” or writing to a private OnceLock would not implement the transition.

Both choices are code/protocol work. Real deployment materials remain necessary after that work, but supplying those materials cannot itself fill the missing transition.

## 7. Independent narrow late-writer adapter

A separate source draft closes the smaller non-Root Config→production Launch construction gap for an **already legitimately admitted** Starting recipient:

- Final manifest: `5befaba241b2f9f908cbd6b758986e7060268fc0`.
- Production source: `2a802e52f81c6cbda3b36b93a7855a8dc4e96f9f`.
- Independent static review: `bb15f4a56f076ddfe14aaa2ce3d596ccb32d1595`.

It keeps the original parser, actual primary runtime inputs, three-right purpose, five-lane activation, exact Root writer FD/Starting checks and Learning/Model connections. It does not rotate authority or acquire an old retained A capability. It is outside the fixed 198947 source audited here; its two negative test methods were not executed for this report. No positive reachability claim is derived from it.

## 8. Minimal lawful follow-up and test boundary

A future implementation must first choose and implement one of the two missing transitions. Before attempting a new runtime, preserve and classify the original source, CURRENT, checkpoint and consumed-nonce state; do not use a potentially sticky-fencing Recover call as an exploratory query with a guessed profile.

For the new-incarnation design, prove actual predecessor retirement and actual successor Starting through the original Supervisor and kernel predicates, then use the original issuer/writer rotation and protected material adoption. The missing historical-source authorization must be separately established before constructing the new Prepared/retained join. For the continuing-incarnation design, use its newly defined original Running transition; do not silently recast it as a restart.

Required negative and uncertainty cases include:

- Old PID with unchanged start time still alive; PID reuse; unrelated process or UID.
- Root/daemon exit before or after registration, CURRENT prepare/publish or witness acknowledgement.
- Pending source or unknown effect outcome; loss of the publication ACK.
- Wrong old/source scope, new identity, original witness, Artifact withdrawal floor or operation profile.
- Previously consumed FinalUse nonce; old authority expiry/revocation; attempts to rearm a closed or cancelled one-shot slot.
- Root session Drop while other capability Arcs remain.

A positive component must execute through the real constructors and actual effect owners. It cannot use the existing synthetic-history parent as proof of an actual A→Dataset→Training owner aggregate. The proposed two-phase fixture was stopped at this source-proven construction conflict; no pseudo-positive branch or extra Root parent was added.

## Evidence classification

This document is static, source-specific analysis. The accompanying RESULT.json lists the exact predicates, source references, independent reviews and the broader earlier cold-recovery report. It does not add to any test count, inherit predecessor native results, or claim that ordinary full-chain, adoption, legal retention/rollback, independent C consumption or physical cold restart has been accepted.
