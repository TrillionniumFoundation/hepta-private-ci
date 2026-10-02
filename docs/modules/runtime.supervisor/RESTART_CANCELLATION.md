# Durable cancellation of pending main restarts

Status: bounded cancellation source mechanism; final-candidate qualification
and the wider stages A-D remain open.

This document amends the pending-restart cancellation item in the supervisor
ownership and recovery documents. It does not replace the full control intent,
process identity, release transaction, or independent acceptance requirements.

The original repair's source-only checkpoint is distinguished below from later
native outcomes in the
[R3 local observation](../../../qualification/runtime-supervisor/LOCAL_EXECUTION_OBSERVATION_20261001_R3.json)
and [R4 local observation](../../../qualification/runtime-supervisor/LOCAL_EXECUTION_OBSERVATION_20261001_R4.json).
The [R4 audit](../../../qualification/runtime-supervisor/ADVERSARIAL_AUDIT_20261001_R4.md)
records candidate scope and remaining gates. These observations record only
their bound source and selected commands; they do not certify a later candidate,
an unfiltered suite or target-host acceptance.

## Existing owner and format

The only persistent writer remains `restart_journal.rs`. Operator Stop/Kill now
cancel the main `pending` field through that owner's existing canonical restart
record. The main budget schema, outer record format, companion domain, checksum
algorithm and physical path are unchanged. No second journal or authority API is
introduced. Calls remain serialized by the existing lifecycle owner.

Cancellation retains the consumed attempt count, window origin and original
eligibility timestamp. It is an idempotent no-op for absent or already-cancelled
state. It does not delete corrupt records, reset budgets or overwrite the
companion's record. Cancellation is explicitly NOT a statement that the process
has exited or that a release transaction completed.

## Control ordering

For an owned active process, `control::stop_slot` first publishes the
Agent/process/generation-bound Stop intent and original stop deadline, then
cancels the durable pending restart
before companion deferral, lifecycle CAS and process signaling. A persistence
failure is returned without an acknowledged Stop or a stop signal. The
in-process queued restart is also disabled; this alone is not a durable
cancellation receipt.

`control::kill_slot` attempts a bound Kill intent and the same durable
cancellation, then attempts the main emergency signal before the companion
signal even if preparation or cancellation failed.
A failed cancellation fences the retained main handle. Cancellation, lifecycle
and process failures still make the operation fail; successful emergency
signaling cannot be described as successful persistence or observed exit.

`stop_runtime_slot` is the private process-control continuation, not an operator
Stop. Restart of a Starting process and an already-admitted deferred Matrix Stop
use it so they cannot accidentally cancel the restart they are implementing.
External callers still enter the existing Supervisor API and daemon fence.

## Pending identity and clocks

Window expiry is evaluated only after checking for an existing pending restart.
An expired budget window therefore cannot silently replace an unresolved claim
with a fresh attempt, reset its attempt count or rewrite its eligibility.

Claim admission, restart preflight and pending recovery use the same validation
for schema, attempt bounds, pending-state consistency and wall-clock rollback
before the recorded window origin. Deterministic clock parameters are private
implementation/test seams; callers do not gain a clock-authority parameter.

This budget component protects claim identity and remaining backoff. The
separate `restart_lineage.rs` binds predecessor/replacement progress but remains
partial; cancellation alone does not close its crash boundaries. Operator Stop
reuses the original deadline from `control_intent.rs` across continuation and
recovery. Restart-internal drain deadlines and durable Matrix quarantine across
daemon generations remain separate gaps.

## Regression sources

`restart_budget_recovery_tests.rs` contains ten tests over the production restart
codec and actual temporary files: unresolved window rollover, remaining backoff,
clock rollback across all three read/admission paths, cancellation/reopen,
exhausted budgets, terminal-window renewal, idempotent no-rewrite, companion
preservation in both directions, corrupt record rejection and invalid policy.

`control_durable_restart_tests.rs` contains eight tests using real temporary
FleetRegistry/lease/restart files and explicit process-driver doubles: Stop and
Kill ordering plus completed-cleanup/reopen, signal failures after cancellation,
corrupt-state Stop rejection, emergency Kill despite corruption, Starting-process
restart and deferred Matrix continuation. The driver observes the actual durable
pending field at signal entry; it is not supplied a claimed cancellation flag.

Targeted native invocations, from the repository `codex-rs` directory:

```sh
just test --locked -p codex-hepta-supervisor --lib restart_budget::recovery_tests
just test --locked -p codex-hepta-supervisor --lib control::durable_restart_tests
```

The complete default and production-authority library/product, format, strict
lint, source-head and deterministic merge suites remain required. These eighteen
functions were the original repair's source inventory at a checkpoint without
Rust/Cargo/rustfmt or direct GitHub/Rust-host access, not passing receipts from
that checkpoint. Later native outcomes are recorded in the observations above.
Existing GitHub checks must establish their own exact-candidate outcomes. No
tests, scripts or workflow requirements are disabled.

## Scope limits and remaining gates

The budget cancellation component is not itself the termination record. Active
Stop and normal Kill admission use the separate durable `control_intent.rs`
record before cancellation and process effects. Emergency Kill still attempts
termination of already-owned handles after failed preparation, while reporting
the failure. Recovery cancels a pending restart
from an unresolved termination intent before restoring a claim, and terminal
completion cannot hide a still-pending restart. Failed or uncertain persistence
remains an error rather than an acknowledged durable operation.

A Stopped/Failed Agent with no owned or leased main/Matrix process and no pending
release transition may cancel a queued restart without inventing an active
process identity. Foreign or unproven leases and unresolved owners still fence
replacement and cannot use that idle shortcut. Complete release/control
supersession and restart-lineage crash closure remain wider requirements; these
bounded paths do not establish an overall "stop never resurrects" claim.

Still required: complete predecessor/replacement crash coverage; restart-internal
cross-daemon deadlines; exit/lease/lifecycle recovery across daemon death; every relevant
fsync/rename/kill-9 boundary; source and merge native qualification; final main
verification; real caller/verifier/process/audit execution; selected Linux/macOS
host faults and 256-instance mixed load; independently issued security/operator
acceptance. Earlier process-lifetime and owned-cleanup repairs are retained, not
re-certified here. Activation, production qualification and release remain false.
