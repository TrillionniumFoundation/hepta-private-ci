# Ordinary retained-A and late-writer feasibility review

Status: **read-only static review; no source changes or execution**. Source: `4e88a3adb244e8c8baca89e526637807c538e11c`. This is a bounded review of the original Q24 launch, retained-source and successor interfaces. It is not a new full-repository caller scan, a positive component result, or a business qualification. Ordinary complete / positive-adoption / ordinary NoUpdate-or-rollback counts remain **0 / 0 / 0**.

The completed V8 archive is independent evidence: Git blob `54018241b0f6b38e1c1d5f24ee95b940f319dc98`, with transfer receipt `6c160ca361838d5a0df63339750e2e73e9563c8e`. It preserves the f913 Root diagnostic's 17 executed, 15 passed and 2 failed, and does not change this reachability conclusion.

## Finding

**The inspected ordinary production APIs do not currently compose a completed A into a fresh, legally admitted successor C.** They provide strongly checked conditional assembly operations, but no product path supplies their retained-A and fresh-launch prerequisites together.

There is a smaller, lawful wiring opportunity: an explicit production caller can invoke the existing late-writer adapter for an **already authorized, genuinely new Starting process**. That would connect an unused entry point without minting authority. It would not carry the old process's retained A capability into that new process, and therefore would not close the learning loop.

This conclusion is limited to the actual original-Q24 path reviewed here. It does not say durable records disappear, nor that all existing low-level recovery APIs are invalid. Those APIs still require their original real owners and do not establish a new cross-incarnation retained-source authorization merely from stored bytes.

## Minimal dependency map

| Step | Existing real interface and required input | Current connection boundary |
| --- | --- | --- |
| Capture completed A | `OriginalCellQ24TaskLedgerProducerV1::retained_learning_source` requires the original producer, an accepted original Decision and Terminal Outcome, its same Prepared/ledger, and its actual original AutomationStore and bounded committed trace. | Returns a private in-process capability. Its fields are not a serialized recovery token; a run ID, receipt, copied trace or new database is insufficient. |
| Bind retained A to learning | `receive_q24_learning_with_retained_capability` / `assemble_q24_learning_with_retained_capability` delegate to actual Root/Q24 assembly, then `with_retained_q24_source` checks the exact initial request, scope, owner set and explicit OriginalQ24 source profile. | These require a legitimate Startup/Launch and Config already available. They do not create a new Starting admission or historical owner. |
| Select waiting C runtime | `AgentdProductionLaunch::prepare_original_q24_successor` calls the private Config/context constructors before `run`. The context requires actual original aggregate, registered retained A, exact scope/request/owners, and the same live Root session. | Pending cannot execute A to obtain its own prerequisite. Its invocation is unavailable until the original publication worker installs the real successor. |
| Run a new launch | `receive_original_late_writer` verifies actual non-Root credentials, receives original three-right writer handoff and five original Root lanes, loads Config through the original Root0600 writer, compares the complete identity and rechecks the live sender. | The adapter is not an authority source. It assumes a real Supervisor Starting process and an independently supplied exact identity comparison. The default CLI does not call it. |
| Execute and observe C | Installed successor resources use the actual `circuit_q24_task_channel_v1`, original published task/model and original authenticated ObjectiveStart path. | The installed invocation delegates to `DurableCircuitTaskSourceV1`, whose learning observation explicitly returns `NonLearning`. Installation is neither a C completion receipt nor automatic next-A learning readiness. |

Capture and binding are defined in [retained source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/cell_q24_retained_learning_source.rs), [retained host entry points](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/production_q24_retained_learning.rs), and [registered source join](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/learning_iteration_retained_source.rs). Successor preconditions are in [launch selection](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/production_q24_successor.rs), [Config selection](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/config_q24_successor.rs), and [actual context](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/learning_iteration_successor.rs).

## Why the two proposed lifecycle routes remain blocked

### Fresh process after A

The original Config loader requires the registry to be **Starting at exactly the supplied spawn generation**. The actual Supervisor start path rejects an existing runtime and an unresolved lease. It transitions Stopped/Failed to Starting and then calls the real process driver. Its exit finalization removes the original lease only after observing `ProcessState::Exited`.

The original Root adoption check also rejects an unchanged peer lifetime and requires real predecessor retirement. A live process with the original PID and start ticks is not retired. Dropping a Root service, waiting for a lease deadline, or changing a fixture lifecycle value cannot substitute for that fact.

Consequently, the previously proposed same-child sequence “keep the retained Arc, stop services, declare a new Starting and reopen Config” does not follow these production lifecycle rules. A real exit destroys that child's in-memory capability. The reviewed retained-source API has no descriptor/receipt-based constructor that re-authorizes this historical owner for the new peer.

Sources: [Config loader](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/config.rs), [Supervisor observed exit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-supervisor/src/tick.rs), [Supervisor start](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-supervisor/src/recovery.rs), [kernel retirement](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/authority_host_checkpoint_publisher.rs), and [Root adoption](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/authority_host_checkpoint_adoption.rs).

### Reuse the same Running owner

This is also not a composition supported by the inspected APIs:

- Config selects one Circuit bootstrap/provider pair and rejects an already selected profile.
- `run_with_shutdown` takes the selected Circuit and learning bootstraps at startup; `Launch::run` consumes Launch and Config. It does not return a mutable Config phase for installing the newly formed Dataset scope.
- Running state retains the task handle, invocation provider and learning-source registration in `OnceLock` fields. The pending-successor selector is a pre-run constructor, not an A-to-C replacement operation for an existing direct runtime.
- Root learning and Model installation consume a prepared Root session before `serve` consumes that session and binds its fixed lanes. The dedicated late generation-publication capability does not install a newly derived learning or Model scope.

Keeping A's process alive preserves the in-memory source, but the current interfaces provide no authorized live phase transition which installs its new scoped learning/Model owner and replaces the original direct task runtime with the waiting successor. Supplying an arbitrary provider/callback, hand-copying a completed snapshot or substituting a public PublishedTask would not establish the original aggregate/session/publication proof.

Sources: [Circuit profile](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/config_circuit_task.rs), [runtime startup](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/runtime.rs), [state fields](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/state.rs), [Root learning installation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/authority_host_learning_session.rs), [Model installation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/authority_host_q24_model_session.rs), and [Root serve](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/authority_host_session.rs).

## What a small lawful late-writer caller could do

The existing adapter is implemented in [production_launcher_late_writer.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/production_launcher_late_writer.rs). Its `expected` argument is only a full-identity equality check. Actual authority comes from the sealed original handoff, live Root session, genuine writer descriptor, actual kernel credentials and original Starting/lease checks.

A dedicated caller could select this entry **before the default Config/root-drop startup path**, in a process which the real Supervisor/Root deployment has already admitted. It must supply the original three-right writer purpose, distinct inherited descriptors, real selected Primary runtime and optional learning/Model purposes, exact expected identity, and the ordinary AuthBus/objective/replay inputs required by the eventual Circuit profile. It must preserve consumption on refusal/cancellation and must not reinterpret the two-right fresh-bootstrap purpose as a fallback.

This is ordinary control-flow/CLI wiring conditional on real supplied capabilities; it does not require a new signer or weaker permission check. However, it is not yet wired: [main.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/main.rs) still uses `Startup::from_process_environment -> receive -> Launch::run`. [CALLERS.toml](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/CALLERS.toml), Git blob `f90e0cf6fe2f024961104821a0f3c1be6256995d`, declares these external product caller sets as empty:

- `agentd_original_late_writer_launch`
- `q24_successor_launch_prepare`
- `production_retained_q24_receive`
- `production_retained_q24_assemble`
- `production_retained_q24_capability_receive`
- `production_retained_q24_capability_assemble`

“External” matters: the retained wrappers do invoke each other inside their defining file and do invoke the original Root assembly. The empty sets must not be misreported as absence of those internal checks. No new full caller scan was executed for this review.

Adding a legitimate caller alone would expose the existing entry for deployments that already have its inputs. It would not supply the missing retained A capability after real peer exit, nor let the same Running A acquire a new Starting identity.

## Exact decisions and real inputs still missing

There are two distinct lifecycle/API decisions, neither implemented by this review:

1. **A historical-source custody protocol for a genuinely new incarnation.** It must obtain and revalidate the actual original source/ledger/journal/witness/database under an explicitly authorized historical read domain, bind the unchanged old source identity and frozen cut to the new live Root consumer, and preserve withdrawal and failure fencing. Serializing the Arc, copying a trace into C's database, or replacing an old source identity is not that protocol.
2. **Alternatively, an explicit live-owner phase transition.** It must define when the same Running owner can register the newly known Dataset scope, drain and transfer its real task resources, and install a different task service under the original session and admission rules. The existing pre-run Config and fixed Root learning/Model lanes do not define that transition.

This is a choice of lifecycle contract, not a request to implement both or loosen existing checks. A positive two-phase component should wait for a selected lawful contract and its real capability source.

Separately, real task input and authenticated task completion, independent observed Terminal Outcome and business labels, already enrolled role/storage capabilities, original independent B data and its existing matched-budget/complete-cost evidence, and actual C ingress/FinalUse inputs remain deployment facts. No code composition should invent them. This review does not change B policy or reinterpret a comparison-contract rejection as NoUpdate.

The C-to-next-A boundary remains explicit: [successor execution](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/circuit_q24_successor_execution.rs) opens the original task channel; [pending invocation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/circuit_q24_successor_invocation.rs) delegates to its real source; [DurableSource](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4e88a3adb244e8c8baca89e526637807c538e11c/codex-rs/hepta-agentd/src/circuit_task_source.rs) returns `NonLearning`. An actual learning producer and independent Outcome would have to be installed through a separately valid, explicit owner path. No automatic feedback or independent C acceptance is claimed.

## Review limits

All findings above are static observations/inferences tied to the source pins in `SOURCE_PINS.json`. This review changed no Rust, metadata, permissions, credentials, refs or PRs and ran no Cargo, native tests, checker or remote process. Existing repeated native/component results are not summed. No same-PID service reopening is called an OS restart.
