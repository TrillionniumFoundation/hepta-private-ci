# Durable cancellation of pending main restarts

Status: bounded source repair; native execution and stages A-D remain open.

This document amends the pending-restart cancellation item in the supervisor
ownership and recovery documents. It does not replace the full control intent,
process identity, release transaction, or independent acceptance requirements.

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

`control::stop_slot` cancels the durable pending restart before companion
deferral, lifecycle CAS and process signaling. A persistence failure is returned
without an acknowledged Stop or a stop signal. The in-process queued restart is
also disabled; this alone is not a durable cancellation receipt.

`control::kill_slot` attempts the same durable cancellation, then attempts the
main emergency signal before the companion signal even if cancellation failed.
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

This protects the existing restart budget's identity and remaining backoff. It
does NOT solve binding a restart to its predecessor and replacement process.
It also does NOT serialize drain/stop deadlines across daemon generations.

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
functions are written regression sources, not passing test receipts. The editing
environment has no Rust/Cargo/rustfmt toolchain and cannot resolve the GitHub or
Rust distribution hosts directly. Existing GitHub checks must establish their
own native outcomes. No tests, scripts or workflow requirements are disabled.

## Scope limits and remaining gates

This repair establishes the source ordering for cancellation of an existing
pending restart on admitted Stop/Kill. It is not a durable Stop/Kill operation
record. A crash after cancellation but before lifecycle/signal publication can
still lose the requested termination while retaining the restart cancellation.
A failed or uncertain publication remains an error, not an acknowledged cancel.

The daemon preflight still requires an active runtime for Stop/Kill; a queued
restart with no runtime needs an explicitly reconciled cancellation admission
path. Release-change continuation is not superseded by this budget-only repair.
Neither gap is converted into an overall "stop never resurrects" claim.

Still required: predecessor/replacement identity; durable non-resetting control
deadlines; exit/lease/lifecycle recovery across daemon death; every relevant
fsync/rename/kill-9 boundary; source and merge native qualification; final main
verification; real caller/verifier/process/audit execution; selected Linux/macOS
host faults and 256-instance mixed load; independently issued security/operator
acceptance. Earlier process-lifetime and owned-cleanup repairs are retained, not
re-certified here. Activation, production qualification and release remain false.
