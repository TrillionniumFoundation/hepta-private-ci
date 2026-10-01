# Optional runtime services and executable identity

`RuntimeTasks` is the public task host used by Agentd, not a second executor.
A composition owner supplies an admitted implementation through
`spawn_optional_service(name, factory, quarantine, retire)`. The factory receives
a child cancellation token. `retire_optional` stops admission, waits for the
service to drain and invokes its route-removal callback. Timeout is not a
successful retirement; failed owner callbacks still fence the host. The task
host never retries an unknown effect or issues a replacement generation.

A service owner must still use its canonical persistent store and its existing
handoff protocol. Stopping a future does not transfer writer ownership.
`AutomationStore::handoff_timer`, for example, advances the durable writer epoch
and leaves the successor draining until explicit resume. Every schedule-creation
path, including `create_task_from_operation`, checks that epoch inside the same
SQLite write transaction as the effect. Historical dedupe receipt replay remains
read-only after retirement. Uncommitted work cannot acquire a receipt from a
rejected old writer.

## Binding a real constructor to the module ABI

`spawn_bound_optional_service(selected, implementation, factory, quarantine,
retire)` connects the existing `RuntimeModuleAbiV1` and
`ActiveRuntimeModuleV1` to this same task host. It validates the implementation
ABI and compares the selected module identity, generation, implementation and
artifact digests, owner, state class, dependencies, ordered versioned ports,
durable domains and effect scope before scheduling a factory. Rejection cannot
start a task or consume a service identity slot. Successful admission continues
through the existing exact-predecessor generation and acknowledged-retirement
checks; this API does not bypass them.

The production TaskFlow constructor currently uses
`spawn_optional_service_generation`, not the ABI-bound entry point. Its concrete
`AutomationStore` must match the Agent identity. An unavailable optional owner
creates no idle placeholder task; supplying no store while the owner is attached
is rejected as inconsistent configuration. The constructor observes the real
timer owner before starting and uses that owner to acknowledge drain.

There is no installed `AgentdState::attach_runtime_module_with_interface` API
or production constructor binding the selected registry ports to the TaskFlow
service. The ABI-bound host API and its rejection tests do not establish that
product integration. Module constructors still need independently declared
versioned interfaces and concrete owner checks before general replacement can be
advertised.

These APIs accept trusted compiled product code. Public ABI values are not
capabilities or independently authenticated selection tokens. The module owner
validates its concrete configuration and current store state; the Supervisor and
durable owners retain selection, migration, writer-handoff and restart duties.
An ABI comparison does not isolate hostile code, authorize an external effect,
prove independent build provenance or establish cross-schema compatibility.

## Repeated replacement and capacity

Legacy names remain single-use. New long-lived composition can use
`spawn_optional_service_generation(name, generation, expected_predecessor,
factory, quarantine, retire)` and `retire_optional_generation(name, generation)`.
The host keeps one greatest-generation fence per logical service. A replacement
must name that exact predecessor, advance its generation and follow an
acknowledged retirement. Pending drain, quarantine and forced abort do not count.
Delayed retirement requests cannot stop the successor. Unversioned APIs cannot
reuse or retire a versioned identity.

Acknowledged replacement reuses one of the 128 identity slots rather than
consuming a slot per generation. Failed registration preserves the prior fence
and acknowledgement and never invokes the factory. `remaining_admission_slots`
reports capacity for new identities, not permission to start a service. New
identities are still bounded, including retired identities. Composition must
plan Supervisor-controlled process-generation rotation before that budget is
exhausted; it must not erase tombstones, rename a failed service or treat a new
host object as a durable recovery checkpoint. No automatic restart is introduced.

The in-memory task fence is not a persistent writer lease. Cross-process recovery
still loads owner state and the Supervisor generation. A new task generation does
not prove compatibility, independent selection or state migration. Stateful
replacement must quiesce/reconcile its owner, acknowledge task drain, commit the
existing durable handoff and explicitly publish the compatible successor. An
unknown effect keeps that sequence blocked. Cross-schema migration requires its
own owner implementation and rollback validation; the same-schema timer tests
below do not establish it.

## Executable identity and retired source

The current Agentd module graph does not install built-in executable observation
or a catalog-state-to-handoff-policy adapter. An earlier executable hashing helper
and state-class parser were source files without a module declaration or active
caller; their sibling tests were consequently never part of the Agentd test
target. They were retired on 2026-10-01 together with four obsolete Objective and
operations host files. Their original source remains in Git history, including
the pre-audit main revision `997e7beef8151160065df36b024bc8da5c989e93`.

The active Objective path is `objective_runtime::ObjectiveRuntimeHost` through
the current RunStart journal, `AgentdState::start_current_run_start_record` and
`AgentdState::start_canonical_intelligence`. It does not run the retired AuthBus
Objective worker or its parallel learning-ledger coordinator. Automation task
creation uses the current control handler and `AutomationStore`; the separate
`automation_effect_host` handles authorized external effects. Neither path
installs the retired automation task-creation operation queue.

Retiring uncompiled files changes no installed runtime path. It also does not
complete executable attestation, independently selected module interfaces,
catalog-state compatibility or general hot replacement. Those require an explicit
product integration and executable tests against the installed constructors.

## Running-service regressions

From the repository root:

```sh
just test --locked \
  -p codex-hepta-agentd --lib runtime_tasks::service_generations --nocapture
just test --locked \
  -p codex-hepta-agentd --lib automation::service_tests --nocapture
just test --locked \
  -p codex-hepta-agentd --test optional_module_restart forty_first_service --nocapture
just test --locked \
  -p codex-hepta-automation --test operation_timer_fence
```

The generation suite fills all 128 identity slots, performs 1,024 acknowledged
replacements of one service and checks bounded retained metadata. It also rejects
stale and unversioned requests, failed callbacks, quarantined predecessors and
unacknowledged drains. Its SQLite test runs 256 service generations through the
public host and the real timer owner, checks old-writer rejection at each handoff,
retains one original operation receipt and reopens the durably retired owner.
The ABI sub-suite rejects incompatible ports, owner, generation, artifact,
authoritative domains and effects before any factory starts, and defines a
512-generation replacement regression through the ABI-bound task entry point.
The TaskFlow service tests exercise its production constructor and actual SQLite
owner, including cooperative drain and uncertain-dispatch rejection.

The existing process test starts a forty-first optional service using the same
public host, executes real SQLite schedule mutations, injects a post-commit task
panic and an abrupt OS-process exit before acknowledgement, and reopens the owner
in later processes. Same-schema replacements advance the actual writer epoch;
stale handles fail and exact requests retain the original dedupe receipt.
Retirement survives process restart and rejects new schedule effects. Required
sibling services exchange real messages before and after lifecycle changes.

The forty required services in that fixture are bounded echo services, not forty
Codex sessions. These suites do not establish complete production App Server
behavior, arbitrary cross-schema migration, multi-host handoff, target-host
capacity, physical-effect completion, independent credential custody or
future-window learning efficacy. No command definition or test source is a
test-pass receipt.
