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

The production TaskFlow constructor uses this boundary. Its concrete
`AutomationStore` configuration must match the Agent identity and an attached
owner must be present in the current runtime topology. The host attachment
advertises `automation.task.v1` and `codex.thread.queue.add.v1`; the compiled
scheduler declares those requirements independently rather than copying the
selected port vectors. A mismatched port version is rejected before its loop can
start. These names identify the in-process `AutomationTaskDraft` and
`ThreadQueueAdd` adapter contract, not a newly negotiated remote protocol.
An unavailable optional owner creates no idle placeholder task. Supplying no
store while the owner is attached is rejected as inconsistent configuration.

`AgentdState::attach_runtime_module_with_interface` keeps the concrete owner
attachment and its port-bearing ABI in the existing registry. Module constructors
can use that boundary without introducing a second registry or changing the core
task supervision algorithm. Other legacy attachments are not silently advertised
as having a versioned interface; they retain their existing empty port vectors
until their own constructors provide real contracts.

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

## Built-in executable observations

Agentd binds built-in implementation identity to the executable bytes plus the
module ID and manifest digest. `candidate_artifact_digest` identifies the
observed executable, not the manifest. The observation is bounded and cached once
per process; the runtime never substitutes a manifest or environment string if
reading the executable fails.

On Linux `/proc/self/exe` names the loaded image, including after unlink or path
replacement. Other targets explicitly report `ExecutablePath`, a weaker
observation that must not be treated as a kernel-attested loaded image. Neither
kind authenticates build provenance, independent review, selection or release.
Concrete versioned ports are now connected for the TaskFlow constructor described
above. Other module constructors still need their own interface bindings before
they can be advertised as a general hot-replacement ABI. An executable hash alone
is not protocol compatibility.

## Running-service regressions

From the repository root:

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd --lib runtime_tasks::service_generations -- --nocapture
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd --lib automation::service_tests -- --nocapture
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd --test optional_module_restart forty_first_service -- --nocapture
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-automation --test operation_timer_fence
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd runtime_executable
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

## Intelligence bootstrap completeness

The ordinary runtime rejects a half-configured canonical Intelligence profile
before opening domain owners or starting tasks. The runner and the authoritative
invocation provider must either both be absent (the explicit compatibility
profile) or both be installed. A runner-only authority configuration is not a
working canonical product profile. This check does not construct owner inputs,
install evaluation trust, select a model or establish a complete learning loop.
`incomplete_intelligence_composition_is_rejected_before_startup` covers the four
presence combinations; owner and run identity validation still happens afterward.
