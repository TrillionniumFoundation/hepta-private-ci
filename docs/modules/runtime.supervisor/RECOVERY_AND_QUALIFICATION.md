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

An unresolved signed intent remains `recovery_required`. Supervisord stays reachable for status and the recovery ceremony, reports not-ready, and rejects ordinary mutation of that Agent except emergency kill. `Running + target release`, process absence, and a local digest-only directive do not independently authorize terminalization.

### 3.1 Inspect the current owner state

The existing inspection command reads the durable signed intent:

```text
hepta-supervisor-intent-recovery inspect <agent-run-root>
```

Record the Agent, grant, intent and release-transaction digests; source/target release identities and immutable manifest/program bindings; current lifecycle generation; and the current daemon authority epoch. Query the daemon's production mutation status and fresh control fence before requesting resolution. A restart can change the lifecycle generation or daemon authority epoch, so do not reuse an earlier recovery decision without revalidating its bindings.

### 3.2 Resolve with independent signed authority

For an ambiguous production transaction, use `ProductionRecoveryDecision` and the existing `ResolveProductionRecovery` RPC (`SupervisordClient::resolve_production_recovery`). The current native Unix daemon requires a production-authority build, an externally pinned verifier and the exact current control fence.

1. Fence the ambiguous process or establish that it is absent. This is a precondition, not operator authorization.
2. Have the independent authority sign a decision binding the exact grant, intent and transaction digests, observed immutable release bytes, current lifecycle generation and current daemon authority epoch. The signer identity/epoch, validity window and signature must match the configured verifier.
3. Select only a supported observed outcome: `Committed` for an upgrade whose durable current release is its target, or `RolledBack` for the matching durable source/rollback target. The decision does not move release state or authorize a guessed outcome.
4. Submit with the fresh control fence. The supervisor re-resolves the Fleet release binding and admission frontier, verifies the decision, then persists the terminal transaction with its `recovery_decision_sha256` before updating the signed intent.
5. Query the durable mutation state after resolution. Rejected authorization leaves the recovery fence in place; a lost response must be reconciled from the durable owner records rather than blindly replayed.

### 3.3 Reconcile an already terminal owner transaction

Recovery also closes the crash cut between terminal release-transaction publication and the matching signed-intent update. It requires the transaction's grant digest, transition kind and source/target identities to match the intent, together with the corresponding durable current/previous release state. Only the proven `Committed` or `RolledBack` outcome is reflected into the intent. An unrelated terminal journal or matching target release alone is insufficient.

### 3.4 Legacy digest-only abort directive

`hepta-supervisor-intent-recovery abort <agent-run-root> <intent-sha256>` remains a legacy command that publishes `supervisor-signed-intent-recovery.json`. It binds an abort request to exact intent bytes but carries no independent signer or signature. The file can be retained for inspection/audit; writing it is not a production recovery authorization. The current supervisor does not consume it to clear a signed recovery fence, publish `Aborted`, or clear pending restart state.

The serialized `Aborted` label is retained for compatibility; it is not a supported `ProductionRecoveryDecision` outcome. Without a verifiable supported decision or an exact matching terminal owner transaction, retain quarantine. Do not delete or rewrite an intent, transaction or lease to make recovery pass.

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
- `tests/signed_intent_recovery.rs` for fail-closed unresolved intent and refusal to clear a production recovery fence with an unsigned digest-only abort directive;
- `supervisor_tests::signed_recovery_requires_pinned_key_and_persists_verified_decision` for wrong-key rejection without durable mutation, independently signed recovery, recorded decision identity and replay refusal;
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
