# runtime.supervisor recovery and qualification runbook

Status: source recovery protocol and qualification plan. This document does not constitute a deployment receipt, independent acceptance, activation, promotion, or release evidence.

## 1. Automatic restart policy

The native supervisor applies one bounded automatic restart policy to the main agent process and the optional Matrix companion:

- recovery window: 300 seconds;
- automatic restart attempt budget: 3;
- exponential delay: 250 ms, 500 ms, 1 s for attempts 1-3;
- the default main-process delays above are bounded by the configured three-attempt budget; changing that budget requires separate qualification;
- a fourth restart request inside the active window is not executed. The main agent records `AutomaticRestartBudgetExhausted`; Matrix records `MatrixRestartBudgetExhausted` and remains degraded;
- explicit `restart` consumes the same bounded main-process budget; an explicit start only clears the durable operator-stop suppression and does not grant unlimited retries; the main budget is not reset by a release change; only an elapsed recovery window replenishes it;
- explicit stop/kill never schedules an automatic restart;
- an unexpected main-process exit while AwaitingHealth, Running or Unhealthy schedules a bounded restart; startup and continuous runtime-health deadlines stop the failed child before replacement; transient health recovery does not itself trigger replacement;
- an exactly identified missing child discovered during recovery may enter the same bounded path; a rejected but potentially live child or an unverifiable lease is quarantined, not treated as proof of absence;
- Matrix readiness recovery does not immediately zero the flap counter, preventing short healthy intervals from bypassing the fixed budget.

### Durable restart counter

The restart counter is persisted in the agent run root as `supervisor-restart-budget.json`. The journal:

- lives under the validated Agent run root; the main counter remains per-Agent across release changes, and each new retry reservation binds its exact `agent_id` and `release_id`; the companion journal binds its independent release window;
- stores independent main-agent and Matrix restart windows;
- is bounded in size and digest-protected;
- is written to a same-directory staging file, file-synchronized, and atomically published with a durable same-directory replacement;
- is restored before daemon recovery decides whether a missing/rejected live child may consume another automatic attempt;
- retains attempts across explicit restart and daemon restart; operator stop/kill persists `operator_stopped` before relinquishing the active control path;
- rejects main restart admission/resumption during wall-clock rollback; the companion restoration treats rollback as exhausted, so neither path obtains a fresh budget;
- fails safe on journal persistence failure: the automatic retry is disabled/exhausted rather than proceeding without a durable counter witness.

The canonical v2 record contains the main restart state and independent Matrix window. Main `pending` identifies a durable reserved attempt. New records set `pending_requires_spawn`: the reservation has not crossed the pre-spawn consumption barrier. `complete_restart` clears the pending reservation **before** calling the physical spawn. Repeated pre-health crashes therefore cannot reuse one pending permit indefinitely. A crash at that barrier may consume an attempt without spawning, but cannot create a free attempt.

Both new boolean fields (`operator_stopped`, `pending_requires_spawn`) default to false and are omitted when false, preserving existing v2 canonical digests. Older executables reject newly present fields; do not downgrade to them as an unverified recovery shortcut. Historical pending records retain their adopted-process interpretation. New pending records resume stopping an adopted predecessor rather than incorrectly treating that predecessor as the replacement. Clock rollback is rejected before resuming a pending deadline. Corruption never resets the budget to an empty record.

The outer canonical record remains version 2; the inner main restart state advances from version 1 to version 2 when an exact retry binding is persisted. Legacy inner version 1 is still readable without adding bytes to its digest. A new pending reservation requires `release_binding`; a different Agent or release cannot reuse it, even before its time window is normalized. Migration preserves acknowledged attempts and never replenishes the budget. Older executables cannot consume the new inner version as a downgrade shortcut.

The retry identity is recorded atomically with the reservation before finalizing the failed process lease. After a first startup failure, no release may have reached `release_state.current` yet. Recovery can then resolve the exact retry binding against the current immutable release catalog, without guessing from configuration or publishing the failed release as selected. Withdrawn releases and mismatched owner identities fail closed. An adopted child handle is retained before any stop/kill signal; a signal failure leaves that same child tracked for bounded escalation.

A persisted stop marker is checked before release-transaction resumption. It suppresses queued restarts and moves an interrupted release into the existing recovery-required protocol. An ambiguous persistence error fences the tracked child and preserves bounded termination rather than reporting ordinary success. Target-host process and filesystem fault receipts are still required for deployment qualification.

## 2. Signed production mutation effect boundary

`apply_production_grant()` has a strict semantic boundary:

1. validate external authority, release binding, lifecycle generation, control revision and transition preconditions;
2. build a `Prepared` signed intent;
3. publish the `Prepared` intent durably;
4. advance the in-memory control revision and queue the existing release transition state machine;
5. publish `Queued` and later `Committed` after the release transition commits.

The `Prepared` publication is the effect boundary. Before that boundary, validation failures are safe rejections. At or after that boundary, an error is reported as `SignedIntentRecoveryRequired`; it must not be reported as an ordinary safe rejection and clients must not blindly replay the grant.

The signed path runs inside `with_slot()`, which temporarily removes the agent slot from `Supervisor::slots`. Signed preflight and revision arithmetic therefore operate directly on the borrowed slot. They must not call helpers that re-query `self.slots` for the same agent.

## 3. Explicit signed-intent recovery ceremony

The supervisor deliberately does not infer success from `Running + target release`. An unresolved signed intent remains fail-closed because those observations do not independently prove that the exact grant caused the current state.

The offline operator directive supports **abort after fencing and confirmed process absence**, not a declaration of target success. Separately, the existing independently signed `resolve_production_recovery` protocol can establish a committed/rolled-back outcome only against the exact intent, transaction, immutable release binding, current admission frontier and current daemon authority epoch. A caller journal or a running target process cannot substitute for that decision.

### 3.1 Inspect

Allow supervisord to normalize an unresolved intent to `RecoveryRequired`, then inspect its current digest. The daemon remains reachable for status while readiness is false. Stop supervisord before writing the offline directive:

```text
hepta-supervisor-intent-recovery inspect <agent-run-root>
```

Record at minimum:

- `agent_id`;
- `grant_sha256`;
- `source_release` / `target_release`;
- `expected_control_revision`;
- `expected_lifecycle_generation`;
- `authority_epoch`;
- `status`;
- `intent_sha256`.

Do not proceed if the run root or agent binding is uncertain.

### 3.2 Authorize abort

Use the exact `intent_sha256` returned by the immediately preceding inspection:

```text
hepta-supervisor-intent-recovery abort <agent-run-root> <intent-sha256>
```

The tool publishes `supervisor-signed-intent-recovery.json`. The directive is digest-bound to the exact unresolved intent; if the intent changes, the stale directive does not apply.

### 3.3 Restart supervisord and reconcile

On recovery, supervisord:

- refuses to infer target success;
- fences/kills an adopted main child and Matrix companion if either is still present;
- remains fail-closed while an ambiguous adopted process is still present;
- only when no ambiguous process remains, persists the intent as terminal `Aborted` and clears pending automatic main restart state;
- then permits normal supervisor recovery to continue.

If status still reports recovery required, verify physical child exit, inspect the current normalized intent again, and restart supervisord. A directive for an older digest is not reusable. Do not delete the intent or lease by hand merely to make startup pass.

`Aborted` means “this grant is terminal and must not be resumed or inferred successful.” It does **not** assert that the source release remained active. A subsequent desired release state must go through a fresh independently authorized transition.

## 4. Crash-consistency qualification matrix

The following are required target-host tests. Source/unit tests are not substitutes for receipts from this matrix.

| Fault point | Required invariant after restart/recovery |
| --- | --- |
| after `Prepared` intent publication | daemon fails closed; request outcome is not reported as a safe rejection |
| after control revision advance | unresolved intent fences replay; revision/state digest cannot imply a clean rejection |
| before child spawn | lifecycle/release state is reconcilable and no stale live lease is accepted |
| after spawn, before process-lease publication | orphan cannot be silently treated as the authorized current child |
| after lease publication | exact identity/generation adoption or rejection is deterministic |
| before/after release-state CAS | current/previous release pair never becomes an unverified mixed state |
| before/after restart-budget journal publication | automatic recovery never gains an attempt because the daemon crashed between counter mutation and durable publication |
| during drain deadline | stop escalation is bounded and lifecycle remains generation-fenced |
| during stop deadline | kill escalation is bounded; later PID reuse cannot satisfy the old lease identity |
| after kill request | restart does not occur for explicit stop/kill; automatic paths still obey budget |
| lease corruption/truncation | fail closed; no blind adoption or deletion of an unverifiable live process |
| restart-journal corruption/truncation | fail closed or disable automatic restart; do not reset silently to a fresh budget |
| intent corruption/truncation | fail closed; no signed transition resumes from guessed state |
| disk full / write failure | no successful receipt unless the required durable state is published |
| fsync failure | ambiguous signed mutation is recovery-required; automatic restart proceeds only with a durable counter witness |
| atomic rename/replace failure | prior valid journal remains authoritative or startup/retry fails closed |
| supervisord SIGKILL | process/lease/release/intent/restart-budget reconciliation satisfies the same invariants after daemon restart |
| repeated child flapping | no more than three automatic restarts per recovery window, including across supervisord SIGKILL/restart |
| wall-clock rollback | rollback never yields a fresh restart budget; the window is conservatively exhausted |

Each receipt must include commit SHA, binary digest, target host identity, OS/kernel/runtime versions, exact fault injection point, before/after durable files, lifecycle/release generations, process identity, restart-journal contents, elapsed timings and final operator-visible outcome.

## 5. 256-instance HOL/load qualification

The daemon retains one authoritative supervisor mutex and Fleet generation/CAS checks. Periodic work releases that mutex between Agents, executes one bounded queued blocking worker at a time, and samples a fresh monotonic clock for each Agent. Exact Agent lookups replace whole-Fleet load/clone calls in tick and snapshot paths. This removes fleet-sized critical sections without introducing a parallel owner.

The existing native health thread also owns typed Drain exchanges. Request queueing is not an acknowledgement. Native Unix connect/write/full-frame reads share one absolute deadline, so a peer trickling bytes cannot extend the exchange forever. Protocol errors are recorded separately from the local Drain/Stop deadlines. None of this makes an indefinitely stalled filesystem operation preemptible; disk latency and global ownership contention remain measured qualification constraints.

Qualification must exercise 256 managed instances and include at least:

- all healthy idle agents;
- simultaneous health polling;
- 10%, 50% and 100% crash/restart waves;
- one intentionally slow process driver operation;
- one intentionally slow filesystem/registry operation;
- concurrent status reads and lifecycle mutations while periodic tick is running;
- Matrix-enabled and Matrix-disabled fleets;
- drain/stop escalation at the same time as unrelated-agent control requests.

Record tick duration, mutex hold duration if instrumented, control RPC p50/p95/p99/max latency, starvation count, missed health/drain deadlines and per-agent recovery completion time. A slow or wedged agent must not silently cause unrelated agents to miss correctness deadlines.

Further lock partitioning requires measured evidence and explicit cross-Agent ordering rules. Do not replace the owner or relax its generation/CAS checks to improve a latency number.

## 6. Release-selection authority boundary

The supervisor implements release transition, rollback and reconciliation. It is not a candidate generator or evaluator and must not self-authorize a production release selection.

The native `hepta-supervisor-release-controller` now consumes an independently signed grant, reads the atomic signing context, durably records its request and observes the owner by exact grant identity. See [production caller mechanics](PRODUCTION_RELEASE_CALLER.md). Source availability is not a current-candidate execution receipt; production completion still requires real Agentd execution and independently deployed authority configuration. Until that composition has its own execution receipts and independent acceptance, describe this module as having a **native release transition engine**, not a completed production release-selection path.

## 7. Source verification identities

Repository-controlled verification for this change includes at least:

- `restart_policy` unit tests for exponential delay, fixed budget and window reset;
- `restart_journal` unit tests for durable round-trip and conservative clock rollback handling;
- `tests/restart_budget.rs`, `tests/restart_budget_recovery.rs` and `tests/fault_recovery.rs` for the real Supervisor state machine with controlled process observations, durable attempts, explicit-stop suppression and daemon reconstruction;
- `tests/signed_intent_recovery.rs` for fail-closed unresolved intent and exact-digest abort terminalization;
- `supervisor_signed_tests.rs` exercises actual signed mutation entry points; `unix_control_io.rs` uses native sockets to bound trickled and oversized frames;
- `signed_history.rs` retains previous grant outcomes, rejects corruption/conflicts and fails closed at capacity;
- the existing release-transition, Matrix companion, lease/adoption, daemon protocol and production-authority tests.

These are test identities, not target-host deployment receipts. CI must pass on the final source commit, and the target-host matrix in section 4 remains required.

## 8. Current claim boundary

This source change can close repository-controlled implementation gaps only after CI passes. It does not by itself close:

- deployed executable qualification;
- target-host crash/fault-injection receipts, including proof of restart-journal durability under real SIGKILL/filesystem faults;
- 256-instance latency/HOL qualification;
- independent operational acceptance;
- production caller/writer composition;
- activation, promotion or release.

## 9. Executable host qualification

Build and run the existing daemon plus the host qualification example from a clean, committed candidate:

```text
cargo build --locked -p codex-hepta-supervisor --features production-authority --bins --example supervisor_host_qualification
target/debug/examples/supervisor_host_qualification ABS_SUPERVISORD ABS_NEW_RECEIPT_JSON 256
```

Run from the Cargo workspace for the build, and from the repository for source identity capture. The example creates an isolated Fleet on the actual `/tmp` filesystem, uses small native OS processes implementing the Agentd control protocol, and retains before/after journals and daemon logs. Its backend is explicitly `native_agentd_protocol_fixture`, **not 256 real Agentd/App Server processes**. It records failures and unmeasured fault classes instead of treating an incomplete run as a pass. Temporary permission faults are restored by a scoped guard; only its own process groups are terminated.

Separate real-product acceptance sets `HEPTA_SUPERVISOR_QUAL_AGENTD` to the built `codex-hepta-agentd` binary before executing `tests/production_release_product.rs`. That test uses isolated configuration, disposable qualification signing keys and no submitted model turn. Neither test installs production trust roots, deploys a release nor establishes independent operational acceptance.


## Linux syscall-fault and current process qualification

`supervisor_host_qualification` exercises actual Supervisor/fixture child processes,
10/50/100-percent crash waves, restart exhaustion, SIGKILL/adoption, explicit-stop
persistence, and malformed and trickling drain peers which ignore SIGTERM. Peer
RPC latency is sampled while the faulty drain is active. Fixture processes are
not the Agentd product binary; the separate real-Agentd signed product test is
mandatory for that claim.

The Linux-only `tests/support/io_fault.c` interposer is compiled by the validation
runner and loaded only into the disposable test Supervisor. A one-shot trigger
inside `/tmp/hsq-*` selects one run directory. It injects actual `EIO` at the parent
`fsync` after atomic publication, or `ENOSPC` on the restart-journal staging write.
A consumed trigger, before/after process states and durable budgets are retained.
This is controlled syscall fault injection, not a full disk, damaged production
filesystem, hardware power loss, or a production-loaded library. No global mount,
disk capacity, live service, credentials, or production trust roots are modified.

The 256-instance Matrix-enabled workload and hardware power loss remain separate
qualification gates; neither is inferred from Matrix-disabled results.
