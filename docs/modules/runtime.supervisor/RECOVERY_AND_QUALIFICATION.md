# runtime.supervisor recovery and qualification runbook

Status: source recovery protocol and qualification plan. This document does not constitute a deployment receipt, independent acceptance, activation, promotion, or release evidence.

## 1. Automatic restart policy

The main process and optional Matrix companion use independent bounded restart domains. Main policy comes from `SupervisorConfig`; its defaults are a 300-second window, three attempts and a 250 ms base delay. Matrix uses the fixed `restart_policy.rs` policy with the same window, budget and initial delays of 250 ms, 500 ms and 1 s. Matrix delay is capped at 30 seconds; main backoff uses checked arithmetic for its configured policy.

Current main-process dispatch rules are:

- A fresh automatic claim follows an exact unexpected exit from an unfenced `Running` runtime, with no release transition, existing pending restart or control retry. `AutomaticRestartQueued` is emitted only after durable budget, lineage and deadline admission.
- An initial `Starting`/`AwaitingHealth` exit does not create a new automatic claim. A health deadline marks the lifecycle failed and stages bounded Stop/Kill containment; the resulting exit does not itself create a new automatic claim.
- A charged replacement that exits before establishing health cancels that pending operation while retaining its consumed attempt. It is not respawned indefinitely under the same charge.
- Constructor `Missing`/`Rejected` adoption does not by itself create a claim. Recovery resumes only an existing durable pending claim whose exact predecessor/replacement lineage permits continuation; an unresolved or rejected lease cannot prove process absence.
- Explicit operator Restart uses the next bounded claim rather than resetting the main budget. Start or a release change does not erase acknowledged main charges. A terminal main window may replenish only after its configured duration expires; a pending claim is retained across window expiry.
- Explicit Stop/Kill durably cancels pending main restart before terminal reconciliation and does not schedule a new automatic restart.
- Automatic main budget exhaustion records `AutomaticRestartBudgetExhausted` and stops further dispatch as a policy outcome; journal, lineage and driver failures remain errors.

Matrix faults use their separate release-bound window. `MatrixRestartBudgetExhausted` leaves the companion degraded. `start_matrix_companion` clears that companion budget only when there is no active release or the selected release has no Matrix command. A new Matrix-enabled release does not refund charges. Recovery does not erase charges merely because the committed release differs from an in-flight adopted release; a healthy readiness observation does not zero the flap counter or reset the main budget.

These rules describe `tick.rs`, `control.rs`, `recovery.rs`, `restart_budget.rs` and `matrix.rs`; they do not promise automatic retries for every startup or adoption failure.

### Durable restart counter

One physical codec in `restart_journal.rs` owns the bounded, digest-protected schema-v2 `supervisor-restart-budget.json` in each Agent run root. Its independent `main` and `companion` fields cannot overwrite one another. The companion retains exact Agent/release binding; main continuation additionally requires the Agent/process-bound `restart_lineage.rs` witness.

- Main state persists its window origin, attempts, pending flag and `next_eligible_unix_ms`. Recovery converts the original eligibility into the remaining delay and reconciles the exact lineage before dispatch. Completion or cancellation clears pending without refunding attempts; ordinary Start and release changes do not reset the main window.
- Matrix persists attempts and window origin but no next-eligible timestamp. Recovery conservatively reapplies the full backoff for the retained attempt rather than accelerating its retry. The no-Matrix-command clear affects only that companion domain and retries a failed persistence acknowledgement.
- The shared record is written to a same-directory staging file, file-synchronized, and atomically published with directory durability acknowledgement. Claim or admission failure cannot authorize a spawn without the required durable witnesses.
- Main wall-clock rollback rejects budget validation and remains fail-closed. Matrix rollback restores an exhausted window and durably normalizes that state before adoption. Neither path grants additional attempts.
- Damaged or ambiguous records deny continuation; source recovery and its pending state must not be rewritten by an operator to create a fresh budget.

The restart-attempt count and main pending eligibility therefore survive supervisord process restart. Durable pending state is not proof that a replacement may launch: exact process ownership, lineage, control-intent cancellation and release admission must still permit continuation. Target-host SIGKILL/fault-injection evidence remains required before claiming deployment qualification.

## 2. Signed production mutation effect boundary

`apply_production_grant()` has a strict semantic boundary:

1. validate external authority, release binding, lifecycle generation, control revision and transition preconditions;
2. build a `Prepared` signed intent;
3. publish the `Prepared` intent durably;
4. advance the in-memory control revision and queue the existing release transition state machine;
5. publish `Queued` and later `Committed` after the release transition commits.

The `Prepared` publication is the effect boundary. Before that boundary, validation failures are safe rejections. At or after that boundary, an error is reported as `SignedIntentRecoveryRequired`; it must not be reported as an ordinary safe rejection and clients must not blindly replay the grant.

The signed path runs inside `with_slot()`, which temporarily removes the agent slot from `Supervisor::slots`. Signed preflight and revision arithmetic therefore operate directly on the borrowed slot. They must not call helpers that re-query `self.slots` for the same agent.

## 3. Legacy offline signed-intent abort ceremony

The supervisor deliberately does not infer success from `Running + target release`. An unresolved signed intent remains fail-closed because those observations do not independently prove that the exact grant caused the current state.

The offline ceremony in this section supports one conservative terminal action: **abort the ambiguous grant after fencing its effects**. It does not prove that the source release is active or that a rollback completed. The separate online signed production-recovery path may reconcile `committed` or `rolled_back` only from an independently signed decision, exact durable transaction and release witnesses, and live daemon fence validation. Follow [PRODUCTION_CONTROL_RUNBOOK.md](PRODUCTION_CONTROL_RUNBOOK.md) for that path; do not run online signed recovery and offline abort concurrently. Neither path permits an operator to mark an unproved outcome successful.

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

## 7. Source verification identities

Repository-controlled verification for this change includes at least:

- `restart_policy` unit tests for exponential delay, fixed budget and window reset;
- `restart_journal` unit tests for durable round-trip and conservative clock rollback handling;
- `tests/restart_budget.rs` for real supervisor crash/restart scheduling behavior inside one daemon lifetime;
- `tests/signed_intent_recovery.rs` for fail-closed unresolved intent and exact-digest abort terminalization;
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

## 9. Executable repository qualification added 2026-09-30

Repository-controlled tests execute the crash matrix for process lease, unified restart record, signed intent and release transaction at file-write, file-sync, rename/hard-link and parent-directory-sync boundaries. Disk-full is represented by the platform `StorageFull` error at the actual writer. Corruption tests truncate each real durable file and require fail-closed decoding. The SIGKILL case uses a separate process, publishes the real four durable records, synchronizes a readiness marker, receives `SIGKILL`, and is inspected by a fresh process.

The 256-Agent test emits one machine-readable JSON line with tick duration, cached status latency, lifecycle-owner latency, mutex wait/hold counters and crash-wave fault counts. Slow-driver and slow-durable-I/O cases deliberately expose serialization. They establish measurable HOL coupling but do not, by themselves, assert a target-host service-level violation. The global lifecycle writer remains until [HOL_REFACTOR_DECISION.md](HOL_REFACTOR_DECISION.md) is satisfied.

The production caller can consume a SHA-256-pinned public authority bundle and the qualification suite covers signer rotation, wrong signer, stale grant, stale daemon-authority epoch and current Fleet revocation. No signing key enters supervisord and no release selection is self-issued. Deployed authority distribution, target-host timing receipts and independent operational acceptance remain external gates.
