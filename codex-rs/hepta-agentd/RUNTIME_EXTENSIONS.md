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

From `codex-rs` (the repository toolchain directory):

```sh
just test --locked --retries 0 --no-fail-fast \
  -p codex-hepta-agentd --lib runtime_tasks::service_generations
just test --locked --retries 0 --no-fail-fast \
  -p codex-hepta-agentd --lib automation::service_tests
just test --locked --retries 0 --no-fail-fast \
  -p codex-hepta-agentd --test optional_module_restart forty_first_service
just test --locked --retries 0 --no-fail-fast \
  -p codex-hepta-automation --test operation_timer_fence
just test --locked --retries 0 --no-fail-fast \
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

## Control drain and exact qualification (2026-09-27 candidate)

The control server owns all accepted connection tasks in one `JoinSet`. It stops
accepting before waiting for acknowledgement within the current two-second
`FRAME_IO_TIMEOUT` grace. Completed request errors do not kill healthy sibling
connections. A task panic or exhausted grace fails the drain; remaining tasks are
aborted and joined before the server returns. The timeout is deliberately not
reported as success. It does not commit an `Indeterminate` run record, interrupt
a physical Codex turn, release a durable reservation, or prove a child process
exited. Those are still the respective coordinator and execution-owner duties.
The enclosing daemon must preserve this failure in its shutdown receipt.

Error frames obtain `current_generation` from the existing Fleet-backed state,
never from the request. Failure to refresh that state closes the connection
without inventing an epoch. Spawn generation identifies the process; current
lifecycle generation may legitimately advance by one for Running and by two for
Draining. Do not reject every `current_generation > spawn_generation` response.
These checks are not a substitute for socket peer credentials.

The Agentd process workflow now requests independent native execution for both
source and prospective-merge lanes on Linux and macOS, even for identical trees.
`--require-native` is an opt-in of the existing candidate planner, not a second
qualification planner. Test commands disable retries and fail-fast. Required
suites are separate steps so a failed owner suite cannot silently suppress E2E
or strict lint. An unavailable build remains a real prerequisite failure, never
an allowed skip. The aggregate must reject any missing, skipped, cancelled or
failed required job and step.

`hepta_agentd_receipt.py` captures the exact App Server fixture before testing and
compares it afterward. The receipt binds source/base/tested SHA, tested tree,
runner OS/architecture, run ID/attempt, fixture path, byte count and SHA-256,
and required step outcomes/conclusions. Both outcomes and conclusions must pass;
`continue-on-error` cannot turn a failure into qualifying evidence. Receipts are
created outside the checkout without overwriting prior evidence. A failed or
missing capture cannot produce a passing final receipt. The workflow retains
failure evidence as well as success evidence.

Scope limitation: this is CI self-recorded evidence of the App Server fixture
and workflow steps, not a signed attestation of every spawned Agentd/worker/test
binary, a count of every executed test, a target-host deployment receipt, or
independent security acceptance. Capture all participating executable and
configuration digests before making a deployment provenance claim.

The new focused regressions can be run with:

```sh
# Repository root: real temporary-Git/subprocess receipt tests, not daemon E2E.
python3 -m unittest -v scripts.test_hepta_agentd_receipt

# codex-rs: native async control tests. A command is not a passing receipt.
just test --locked --retries 0 --no-fail-fast -p codex-hepta-agentd --lib \
  control::shutdown_tests --test-threads=1
```

## Operator qualification and recovery protocol

This is a proposed acceptance protocol, not an assertion that target-host tests,
telemetry, deployment identity or the canonical execution chain already exist.
The deployer and an independent reviewer must name the target and approve its
load profile before executing it. Do not activate on the strength of this text.

| Gate | Required observation | Current evidence rule |
| --- | --- | --- |
| Exact source | Required CI and architecture checks, native Linux/macOS source and merge jobs, unchanged source, matching digests | Retain run IDs and attempts; an old head or skipped job does not qualify a new head |
| Dispatch/recovery | Formal ingress reaches physical start, interrupt and terminal observation; crash at every durable boundary; no redispatch of an uncertain effect | Direct coordinator/driver fixtures do not prove the canonical path |
| Authority | Current revocation/epoch/generation/digest checks linearized with durable admission; no forgeable public admission handle | Caller convention and a boolean checked flag are insufficient |
| Ownership | One fenced writer across kill/restart and successor handoff, including Neuron lifetime | Joined async futures alone do not prove process or writer termination |
| Capacity | Declared concurrency, socket pressure, sustained load and soak on the named host, bounded RSS/FD/task growth and measured latency | CI echo services are not a production capacity result |
| Faults | Disk full, corrupt state, rename/fsync failure, stale generation and worker death retain uncertainty and deny unsafe replay | Never inject faults into the only production state copy |
| Acceptance | Independent review and deployment provenance with explicit release/activation decision | CI receipts always leave production activation false |

### Incident handling

On acknowledgement timeout, task panic, `Indeterminate`, or failed drain, stop new
admission through the existing supervisor-controlled lifecycle. Preserve the
original operation/run identity, spawn/current generation, revision, executable
and configuration digests, and owner evidence. Query the durable execution/effect
owner using that same identity. Do not issue a fresh ID, remove a tombstone, reset
an epoch, or infer “not applied” from a closed socket. An unknown outcome remains
unknown until the owner supplies an authoritative terminal or negative receipt.

On corrupt or unavailable Fleet/owner state, fail closed. Preserve a forensic
copy and identify a validated checkpoint through the existing owner recovery
protocol. Do not edit journal/SQLite rows or substitute a cached generation just
to restore readiness. Validate recovery on an isolated copy before switching the
live service. Recovery must preserve dedupe identities and revocation floors.

On overload, distinguish a bounded admission rejection from accepted work whose
acknowledgement was lost. Reduce offered load; preserve the original accepted
identity for reconciliation. Do not respond by unbounding connection/task limits
or by enabling production mutation features without their authority owner.

### SLO, alerts and rollback acceptance

Before deployment, record a concrete workload envelope and numeric budgets for
control p95/p99 latency, dispatch and terminal latency, cancellation acknowledgement,
drain completion, RSS, open descriptors and queue depth. These must be measured
on the target; no universal latency SLO is claimed here. A proposed soak profile
is 24 hours at the declared capacity with repeated drain/restart under load.

Correctness budgets are zero duplicate external dispatches, zero stale-writer
acceptances, zero fabricated terminal successes and zero successful forced-drain
receipts. Page immediately on any such violation, corrupted owner state or lost
identity binding. Alert on sustained capacity exhaustion, rising indeterminate
backlog or exhausted drain budget. Metric names, exporters and alert rules still
require implementation and a tested delivery path; this document is not that
instrumentation. Keep run IDs and digests in access-controlled logs, not metric
labels; do not log prompts, credentials or authority key material.

Rollback requires closing admission, reconciling accepted work, fencing the old
writer, verifying the predecessor binary/configuration and schema compatibility,
and using the existing explicit owner handoff. Preserve unresolved effects and
revocation floors. Binary rollback is not permission to roll back durable state
or replay requests. Validate readiness and read-only inspection before reopening
admission. Abort rollback when compatibility or ownership cannot be established.

Record independent reviewer, target identity, exact commits/digests, fault/load
profile, observed results and rollback evidence outside mutable build output.
A proposed promotion criterion is three consecutive complete main-branch native
runs without retries or allowed skipped lanes, followed by independent target-host
acceptance. Neither this candidate nor its CI recorder grants merge, release or
activation authority.
