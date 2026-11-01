# Signed-intent abort: blocked activation and smallest coherent repair

Status: **not activated, original recovery quarantine retained**. This is an interface design and evidence-backed implementation boundary, not a completed Rust patch or a native validation receipt.

## Current exact behavior

The examined source is head `1e91c5cf18272505508b9ce880fd34879bb6a546`. GNU job `124814581056` fails `exact_digest_abort_terminalizes_unresolved_intent`. Its first assertion still expects `recover` to return an error, although current recovery intentionally keeps the daemon reachable while quarantining the unresolved grant. The deeper assertion requires a persisted `Aborted` intent; no current recovery path consumes the CLI's exact-digest abort directive.

Do not fix the test by removing the terminal-abort assertion. Do not add `Aborted` unconditionally to the early terminal match. `preflight_start` and the lower `start_release_slot` do not independently reject unresolved release transactions; the ordinary daemon mutation gate currently relies on the signed recovery status. That one-line change can therefore remove a useful fence.

## Why the six checks are currently insufficient

The desired checks are: a valid exact-digest directive; exact agent binding; no live Agent runtime; no live Matrix runtime; no pending Agent or Matrix lease; a current terminal lifecycle; and no unresolved release transaction or queued restart/release action. They must describe one protected version of the state until the terminal intent is durably published.

`SingleInstanceLock` protects the daemon's entire run and its async mutex serializes its RPC and tick paths. The public `Supervisor::recover` API has neither a guard argument nor an owned guard field. `FleetRegistry` holds only a layout. Its hard-link lifecycle publication serializes competitors for one next generation; it does not cover the other journal files. Intent publication reads the existing intent and then atomically replaces its file, without an expected-current-digest comparison protected through replacement. The CLI directive writer also does not participate in the daemon lock.

The deterministic `audit_abort_interleaving.py` executes the relevant real filesystem primitives on explicitly synthetic records. It demonstrates two schedules: a new lifecycle/lease can be published after an abort reader checks them, and a committed same-grant intent can replace the checked unresolved intent before a stale abort writer replaces it again. A control confirms that competing writes to the *same* lifecycle generation are rejected. These are counterexamples to a proposed naive fix, not claims that the absent abort path currently performs these unsafe writes.

There is also a separate process-evidence gap. In `matrix.rs::recover_matrix_companion`, the non-exact `Adoption::Adopted` branch calls `kill`, removes the lease, and drops the handle. The `ManagedProcess` trait explicitly requires every method, including `kill`, to return without waiting for exit. Runtime absence plus lease absence after that path does not establish that the old process is gone. Failed or rejected adoption must likewise remain indeterminate when it cannot prove absence.

## Proposed interface changes

### 1. One lifetime owner capability

Move the existing fleet-level exclusive owner mechanism into a small reusable module at a dependency level usable by both Fleet and Supervisor. A proposed `FleetRuntimeOwner` has private fields, holds the OS lock file, is not clonable, and is bound to the validated physical fleet root. It uses the same supervisor lock path and fail-closed unsupported-platform policy. This must retain existing ownership, permissions and path validation guarantees rather than introduce a second unrelated lock.

`Supervisor::recover` acquires and stores this guard for the full `Supervisor` lifetime. The daemon calls the same constructor and removes its separate acquisition; it must not nest-lock the same path. Every `start`, restart, release transition, recovery and tick effect then runs while the supervisor owns the guard. A second direct library supervisor must be rejected just as a second daemon is rejected. Existing tests that deliberately model handoff must release the prior owner before reacquisition.

Acquiring a temporary lock only around the new abort helper is insufficient: another public supervisor could already own an active runtime without participating in that temporary lock.

### 2. Protected mutation APIs, not a public boolean

Expose a scoped runtime writer borrowed from the owner, for example `FleetRegistry::runtime_writer(&mut FleetRuntimeOwner) -> FleetRuntimeWriter<'_>`. The actual type and placement must avoid a Fleet-to-Supervisor dependency cycle. Bind the writer to the same fleet root and agent when opening per-agent state.

Require that writer for lifecycle and release-state mutations. Remove or migrate public escape paths that can mutate the same protected runtime records without the guard. Keep read-only registry APIs independent. Registration and immutable catalog publication need separate analysis: they must not mutate a registered agent's protected runtime snapshot behind the owner.

Internal intent, release-transaction, restart-budget and lease writers must receive a borrowed owner context or be reachable only through the owned supervisor writer. The CLI must also acquire the same owner while stopped, validate the fleet/agent binding, and reread the intent under that owner before publishing a directive. Its current `<agent-run-root>` interface does not itself carry a validated fleet owner; either resolve it through validated layout/registry identity or introduce an explicit fleet-root/agent interface with a documented compatibility transition. A raw boolean such as `owner_locked = true` is not a proof.

### 3. Versioned abort snapshot and durable order

Under the same owner, read and validate one `AbortRecoverySnapshot` containing the agent ID, current lifecycle generation and state, release-state generation, exact intent digest, exact directive digest, transaction digest/phase, both lease states, both runtime observations and queued restart/release actions. Absence must be a successful validated observation; parse/I/O/adoption failures are indeterminate.

Only the exact current unresolved intent may be aborted. Compare the expected intent digest again within the protected publication operation. A change, mismatch or any unresolved resource keeps the original quarantine. The terminal record means the grant was aborted; it must not assert that the source release is current or that a target operation succeeded. Keep independent release, generation, lease and authority fences intact.

Crash ordering must be specified before enabling this path. Pending automatic restart state must not become an implicit command after a crash between abort publication and restart cleanup. The durable abort/recovery fence should suppress pending autonomous actions until their cleanup and exit observations have been reconciled. Restart or release state must not be silently deleted merely to satisfy an absence test.

### 4. Preserve exact process-exit evidence

Keep an adopted Matrix runtime and its lease after requesting termination, marked fenced and stopping/killing, until `poll` observes the matching process exit. A failed kill must remain retryable. Only exact observed exit or a positively established missing process may discharge that resource. A rejected identity is not equivalent to proven absence of the old process.

Do not block waiting inside `kill` or add sleeps/timeouts. Use the existing nonblocking tick state machine. Reconcile it without rescheduling Matrix or main automatic restarts while a signed recovery fence is active.

### 5. Preserve independent admission fences

Separate explicit operator Start admission from the internal authorized release-transition startup helper. The latter legitimately starts a target while a transaction is nonterminal, so a blanket rejection inside `start_release_slot` would break valid upgrades and rollbacks.

Explicit Start/public start-release and autonomous restart scheduling must reject unresolved signed recovery, unresolved release transactions and outstanding process resources. Internal target startup must require the exact owner-held transaction and generation that authorize it. An already persisted `Aborted` intent can be kept terminal only while these independent fences remain enforced; its status alone must not enable mutation.

## Writer coverage and validation required before activation

`WRITER_INVENTORY.json` lists the exact inspected source definitions and call sites for the current supervisor-owned records. The two public Fleet mutation APIs and the exported recovery directive writer are the interfaces that prevent a local helper from establishing the owner invariant by itself. Search results were discovery hints; recorded call sites are from the verified head files, with test-only call sites identified separately.

Required native regression cases include concurrent daemon versus direct-library acquisition, owner handoff after drop, wrong-root owner rejection, stale intent/directive/lifecycle/release versions, both retained live runtimes, both pending leases, unreadable or corrupt records, rejected adoption, a kill that returns success while the process remains live, transaction-recovery fences, pending automatic restart, and already-Aborted recovery with an independent unresolved transaction. Keep the original exact-abort integration assertion and add these negative cases before enabling the writer.

Fault-injection must cover the durable boundaries between fenced exit, restart suppression, intent publication, and cleanup. Original native process tests on the supported platforms and the repository's `just test -p codex-hepta-supervisor` / formatting gates remain required. The current filesystem witnesses are deliberately not substitutes for those tests.

## Implementation assessment

A correct repair is feasible within the existing single-owner architecture, but it is not a safe one-function or one-test change. At least the owner guard, daemon/public constructor integration, protected Fleet mutation APIs, CLI writer, Matrix recovery retention, and independent admission paths must move coherently. Split these into reviewed stages that preserve quarantine until the final stage; do not activate the abort path in an intermediate stage. No such product source change is included in this evidence package.
