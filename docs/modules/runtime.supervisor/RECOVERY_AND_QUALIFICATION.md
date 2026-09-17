# runtime.supervisor recovery and qualification runbook

Status: source recovery protocol and qualification plan. This document does not constitute a deployment receipt, independent acceptance, activation, promotion, or release evidence.

## 1. Automatic restart policy

The native supervisor applies one bounded automatic restart policy to the main agent process and the optional Matrix companion:

- recovery window: 300 seconds;
- automatic restart attempt budget: 3;
- exponential delay: 250 ms, 500 ms, 1 s for attempts 1-3;
- the delay function is capped at 30 seconds if the fixed budget is changed in a future reviewed revision;
- a fourth restart request inside the active window is not executed. The main agent records `AutomaticRestartBudgetExhausted`; Matrix records `MatrixRestartBudgetExhausted` and remains degraded;
- explicit operator restart/new release start resets the in-memory recovery budget;
- explicit stop/kill never schedules an automatic restart;
- an unexpected main-process exit while Starting/AwaitingHealth or Running schedules restart; a health-deadline failure schedules restart after the failed child exits;
- a missing/rejected live child discovered during supervisor recovery enters the same bounded restart path;
- Matrix readiness recovery does not immediately zero the flap counter, preventing short healthy intervals from bypassing the fixed budget.

### Persistence boundary

The restart-window counter is currently supervisor-process memory. A supervisord process restart reconstructs process/release state from FleetRegistry and leases, but does not yet reconstruct the prior restart-window counter. Therefore the source now enforces the dossier budget during one supervisord lifetime, while a host-level crash/restart can reset the counter. Treat durable cross-supervisord restart budgeting as an open crash-consistency qualification item; do not claim the recovery-window budget is host-crash durable until a durable counter witness is implemented and exercised.

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

The repository-controlled recovery ceremony currently supports one conservative terminal action: **abort the ambiguous grant after fencing its effects**. It does not support an operator command that simply marks the target successful.

### 3.1 Inspect

Run while supervisord is stopped or has failed closed:

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

If startup still reports `signed_intent_recovery_required`, verify that the fenced child actually exited and start supervisord again. Do not delete the intent or lease by hand merely to make startup pass.

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
| during drain deadline | stop escalation is bounded and lifecycle remains generation-fenced |
| during stop deadline | kill escalation is bounded; later PID reuse cannot satisfy the old lease identity |
| after kill request | restart does not occur for explicit stop/kill; automatic paths still obey budget |
| lease corruption/truncation | fail closed; no blind adoption or deletion of an unverifiable live process |
| intent corruption/truncation | fail closed; no signed transition resumes from guessed state |
| disk full / write failure | no successful receipt unless the required durable state is published |
| fsync failure | ambiguous signed mutation is recovery-required, not safe rejection |
| atomic rename/replace failure | prior valid journal remains authoritative or startup fails closed |
| supervisord SIGKILL | process/lease/release/intent reconciliation satisfies the same invariants after daemon restart |
| repeated child flapping | no more than three automatic restarts per in-memory recovery window; durable host-restart behavior remains an explicit open item until persisted |

Each receipt must include commit SHA, binary digest, target host identity, OS/kernel/runtime versions, exact fault injection point, before/after durable files, lifecycle/release generations, process identity, elapsed timings and final operator-visible outcome.

## 5. 256-instance HOL/load qualification

The daemon currently serializes supervisor mutation/tick work through one async supervisor mutex. This is a correctness-preserving design but has a possible head-of-line latency cost because registry, filesystem and process-driver work occurs while the lock is held.

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

If the evidence shows unacceptable HOL blocking, the next architecture change should split collection/effect/application phases or introduce per-agent serialization while retaining FleetRegistry generation/CAS fences. Do not partition locking before the measurement demonstrates the need and the new ordering rules are specified.

## 6. Release-selection authority boundary

The supervisor implements release transition, rollback and reconciliation. It is not a candidate generator or evaluator and must not self-authorize a production release selection.

Production completion still requires an independently composed caller/writer/authority path that produces the signed grant consumed by the supervisor. Until that composition has its own execution receipts and independent acceptance, describe this module as having a **native release transition engine**, not a completed production release-selection path.

## 7. Current claim boundary

This source change can close repository-controlled implementation gaps only after CI passes. It does not by itself close:

- deployed executable qualification;
- target-host crash/fault-injection receipts;
- 256-instance latency/HOL qualification;
- durable restart-budget continuity across supervisord process restart;
- independent operational acceptance;
- production caller/writer composition;
- activation, promotion or release.
