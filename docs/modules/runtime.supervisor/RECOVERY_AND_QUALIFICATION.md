# runtime.supervisor recovery and qualification runbook

Status: source recovery protocol and qualification plan. This document does not constitute a deployment receipt, independent acceptance, activation, promotion, or release evidence.

## 1. Automatic restart policy

The native supervisor bounds restarts for the main agent process and the optional Matrix companion. The default main-agent configuration and the Matrix policy use:

- recovery window: 300 seconds;
- automatic restart attempt budget: 3;
- exponential delay: 250 ms, 500 ms, 1 s for attempts 1-3;
- a fourth restart request inside the active window is not executed. The main-agent path returns `SupervisorError::RestartBudgetExhausted(agent_id)`, which `tick()` reports as an `AgentFault` and records as `DriverFault` with the same error message. Matrix records `MatrixRestartBudgetExhausted` and remains degraded;
- a main-agent restart claim records `RestartQueued`; the attempt count and pending intent are owned by the durable main budget. `AutomaticRestartQueued` and `AutomaticRestartBudgetExhausted` remain enum variants but are not emitted by the current main-agent path;
- explicit main-agent restart consumes the same durable budget. Starting a process or changing release does not erase consumed main-agent attempts; the next claim resets the count only after the configured recovery window expires;
- explicit stop/kill never schedules an automatic restart;
- an unexpected main-process exit schedules a fresh automatic claim when the runtime is Running, is not fenced, and has no release transition or restart already pending. Startup and health-deadline failures do not independently enter this Running-exit path;
- daemon recovery restores an already published pending main claim. A missing runtime is queued against that same attempt; an adopted replacement satisfies the existing claim without another spawn;
- Matrix readiness recovery does not immediately zero the flap counter, preventing short healthy intervals from bypassing the fixed budget.

These main-agent event and fault semantics were introduced together with behavior tests in commit [`de9a048d87d2`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/de9a048d87d2252ae2230784c75a79549d9e1653). The crash-boundary ordering was tightened in [`f73a1e308dbd`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/f73a1e308dbd00a410d5be6edc30db3a5769f194). Qualification must observe the durable counter, pending state, process count and error outcome rather than require the older automatic-event variants.

### Durable restart counter

The restart counter is persisted in the agent run root as `supervisor-restart-budget.json`. The canonical schema-2 record has separate `main` and `companion` fields, written through one owner codec. The record:

- stores the main-agent budget for that run root independently of the companion journal, which is bound to the exact `agent_id` and active `release_id`;
- preserves each restart domain when the other domain is updated;
- stores `main.attempts`, `main.pending` and the wall-clock `main.next_eligible_unix_ms` deadline. A successful claim is published before lifecycle/lease exit finalization, and healthy completion clears pending state without resetting the attempt count;
- is bounded in size and digest-protected;
- is written to a same-directory staging file, file-synchronized, and atomically published with a durable same-directory replacement;
- restores a pending main claim with its remaining delay. Replaying that claim consumes no additional attempt, and recovery of a healthy replacement preserves the completed attempt count for its next failure;
- does not let a companion release change overwrite the main budget;
- treats wall-clock rollback conservatively: a new main claim fails if the clock precedes its recorded window origin; companion recovery restores the affected window as exhausted;
- fails safe on journal persistence failure: the automatic retry is disabled/exhausted rather than proceeding without a durable counter witness.

The restart-attempt count and pending eligibility deadline therefore survive supervisord process restart. Recovery reconstructs a monotonic deadline from the persisted wall-clock deadline; it does not promise an identical elapsed delay if the wall clock changes. The shared record and preservation rules were consolidated in commit [`ba97f175566c`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/ba97f175566cdb0d31b0b5fe034ca0e98d8ba969). Target-host SIGKILL/fault-injection evidence is still required before claiming this behavior is deployment-qualified.

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

Recovery keeps supervisord reachable for read-only status and recovery queries while quarantining the affected Agent. Ordinary mutation remains refused. An ambiguous outcome becomes terminal only through an exact durable release-transaction witness or the existing independently signed `ResolveProductionRecovery` protocol. A digest by itself does not establish the effect's outcome.

### 3.1 Inspect

Inspect the retained owner state without mutating it:

```text
hepta-supervisor-intent-recovery inspect <agent-run-root>
```

Retain `agent_id`, `grant_sha256`, `source_release`, `target_release`,
`expected_control_revision`, `expected_lifecycle_generation`, `authority_epoch`,
`status` and `intent_sha256`, together with the exact release transaction and
current daemon authority epoch. Do not substitute a different run root or infer
success from a matching currently running release.

### 3.2 Reconcile through the original signed protocol

The existing `ResolveProductionRecovery` request requires an independently
signed decision binding the grant digest, intent digest, release-transaction
digest, observed immutable release bytes, current lifecycle generation and
current daemon authority epoch. The supervisor revalidates the current Fleet
admission frontier before publishing `Committed` or `RolledBack`.
An absent or mismatched transaction, changed release binding, invalid signature
or still-unfenced ambiguous process keeps recovery required. The request does
not replay the original transition.

The legacy command
`hepta-supervisor-intent-recovery abort <agent-run-root> <intent-sha256>`
now exits unsuccessfully before writing a directive. Older versions wrote
`supervisor-signed-intent-recovery.json`, although the current supervisor did not
consume that unsigned file. Existing legacy files cannot terminalize an
ambiguous intent; even an exact digest leaves it quarantined. Do not delete the
intent or lease to make startup appear healthy, and do not interpret the old
command's successful exit as a recovery receipt.

### 3.3 Recover and verify

On recovery, supervisord hydrates the durable intent even if process adoption
fails. It fences the affected generation, requests termination of an adopted
unfenced child, and exposes `recovery_required` through status while refusing
ordinary mutation. Repeated startup or a legacy abort directive does not infer
a successful, rolled-back or aborted outcome. Validate the separately signed
resolution and retained terminal transaction through the original owner before
accepting a resolved state.

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
- `tests/restart_budget.rs` for supervisor crash/restart scheduling with a controlled process driver inside one daemon lifetime: exact durable attempts and pending state, 250/500/1000 ms backoff, four total spawns and the complete budget-exhaustion fault;
- `tests/restart_budget_recovery.rs` for the same budget and timing invariants across three daemon recoveries around an admitted release and adopted live children;
- `tests/signed_intent_recovery.rs` for retained quarantine, actual legacy-CLI refusal without publishing a directive, readable original status, and ordinary-mutation refusal even after a historical exact-digest abort file is present;
- the existing release-transition, Matrix companion, lease/adoption, daemon protocol and production-authority tests.

These are test identities, not target-host deployment receipts. CI must pass on the final source commit, and the target-host matrix in section 4 remains required.

For the real paired-process scenarios, use the existing small-artifact profile:

```sh
just test --locked -p codex-hepta-supervisor --cargo-profile dev-small \
  --test paired_process_product --test-threads 2 --retries 0
```

These tests install and revalidate the actual child executable through Fleet's
immutable release bundle. A large debug test ELF also carries nonloaded debug
and symbol data through every complete-file hash. On the measured Linux host
without SHA instructions, a 301,348,648-byte debug fixture required about
19 seconds for each unoptimized SHA256 pass, exceeding the 60-second harness
watchdog during installation before a child could start. `dev-small` already
omits debug data and strips symbols; it retains the same source, real children,
full-file sealing, immutable-byte checks and lifecycle deadlines. Record the
actual profile and ELF hash with every run. A stripped measurement clone is
only a hash-cost comparison, not evidence that the product scenarios passed.
The code-owned Nextest policy serializes these two process scenarios across
test processes. Only the five-pair scenario has a 120-second outer watchdog:
the measured small-artifact run reached ten healthy children at about 55 seconds
before completing five immutable-bundle adoption checks. The fixture's original
60-second health/ready, 2-second drain and 1-second stop deadlines remain intact.
This is a bounded test-workload allowance, not a product latency acceptance claim.

## 8. Current claim boundary

This source change can close repository-controlled implementation gaps only after CI passes. It does not by itself close:

- deployed executable qualification;
- target-host crash/fault-injection receipts, including proof of restart-journal durability under real SIGKILL/filesystem faults;
- 256-instance latency/HOL qualification;
- independent operational acceptance;
- production caller/writer composition;
- activation, promotion or release.
