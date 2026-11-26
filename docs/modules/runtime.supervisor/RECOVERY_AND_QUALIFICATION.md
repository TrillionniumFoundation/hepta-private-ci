# runtime.supervisor recovery and qualification runbook

Status: source recovery protocol and qualification plan. This document does not constitute a deployment receipt, independent acceptance, activation, promotion, or release evidence.

## 1. Automatic restart policy

The default main-process configuration and the separate Matrix companion policy use:

- recovery window: 300 seconds;
- restart attempt budget: 3;
- exponential delay: 250 ms, 500 ms, 1 s for attempts 1-3;
- Matrix's scheduling helper caps its delay at 30 seconds. The canonical main-process port uses checked exponential multiplication of its configured base; custom settings must be reviewed against that implementation;
- a new main restart claim after three consumed attempts inside the active window is rejected; replay of an existing pending claim within that active window retains its recorded attempt. The automatic main-exit path records `AutomaticRestartBudgetExhausted` after successful exit finalization; Matrix records `MatrixRestartBudgetExhausted` and remains degraded;
- an admitted explicit main `Restart` uses the same durable claim and backoff, so it counts against the same main budget;
- new automatic main claims are admitted for an unexpected, unfenced `Running` exit with no release change or already-pending restart. `Starting`/`AwaitingHealth`, health-timeout shutdown and `Draining`/`Stopping`/`Killing` exits are outside that branch;
- recovery validates/adopts the existing lease and requeues an already-persisted main pending claim when no runtime was adopted. A missing or rejected child alone does not establish a new restart claim;
- Matrix readiness recovery does not immediately zero the flap counter, preventing short healthy intervals from bypassing the fixed budget.

### Durable restart record and local deadlines

`supervisor-restart-budget.json` has one bounded, digest-protected schema-2 codec for two separate records:

- the canonical per-Agent main record stores its attempt count, wall-clock window origin, `pending` flag and `next_eligible_unix_ms`;
- the companion projection stores an Agent/release binding and Matrix window. Its legacy main-window projection must be empty; ordinary companion writes preserve the canonical main record;
- the codec reads supported legacy records conservatively, preserving acknowledged main attempts, and rejects malformed, oversized or digest-inconsistent records;
- publication writes a same-directory staging file, synchronizes that file and calls the existing durable same-directory publisher. Publication failures remain errors and require reconciliation of the retained state;
- a new main claim is published before lifecycle/lease exit finalization. Process adoption is attempted during recovery, then the main pending record is hydrated before normal ticking;
- a healthy replacement completes the main pending claim while retaining its attempt history. Neither a companion projection update nor a daemon restart supplies a fresh main budget;
- main-path persistence errors propagate. A Matrix restart-scheduling persistence failure clears its local retry time and marks its retry state exhausted.

The main pending claim survives supervisord restart: `pending_restart` returns the recorded attempt and computes the remaining delay from `next_eligible_unix_ms` and the current wall clock. Recovery rebuilds an in-process `Instant` deadline from that delay; an already-adopted runtime satisfies the same pending attempt instead of being queued as a second replacement. Thus the serialized claim and eligibility time are durable state even though an `Instant` value cannot be carried across processes. A lost process-local timer is not an instruction to discard an acknowledged pending claim.

The main claim path rejects a wall clock earlier than its stored window origin. Pending recovery uses a saturating remaining-time calculation, so a wall-clock jump can change the reconstructed wait; the record is not a promise of exact elapsed real time or a successful process start. The companion window/restoration helper has its own conservative rollback rules and does not define the main pending-claim protocol. Inspect the current [main budget port](../../../codex-rs/hepta-supervisor/src/restart_budget.rs), [recovery path](../../../codex-rs/hepta-supervisor/src/recovery.rs) and [shared record codec](../../../codex-rs/hepta-supervisor/src/restart_journal.rs) when qualifying these boundaries.

Target-host SIGKILL, clock-change and publication-failure evidence remains required. These source rules do not establish power-loss durability, exact scheduling or successful restart on an unqualified host.

## 2. Signed production mutation effect boundary

`apply_production_grant()` has a strict semantic boundary:

1. validate external authority, release binding, lifecycle generation, control revision and transition preconditions;
2. build a `Prepared` signed intent;
3. publish the `Prepared` intent durably;
4. advance the in-memory control revision and queue the existing release transition state machine;
5. publish `Queued` and later `Committed` after the release transition commits.

The `Prepared` publication is the effect boundary. Before that boundary, validation failures are safe rejections. At or after that boundary, an error is reported as `SignedIntentRecoveryRequired`; it must not be reported as an ordinary safe rejection and clients must not blindly replay the grant.

The signed path runs inside `with_slot()`, which temporarily removes the agent slot from `Supervisor::slots`. Signed preflight and revision arithmetic therefore operate directly on the borrowed slot. They must not call helpers that re-query `self.slots` for the same agent.

## 3. Independently signed recovery of a quarantined transition

The current recovery contract is defined by the [technical guide](TECHNICAL.md#8-failure-semantics-recovery-and-rollback) and the signed recovery owner entrypoints. An ambiguous signed transition remains `recovery_required`. Supervisord stays reachable for status and the recovery ceremony, reports not-ready, quarantines the affected Agent generation and rejects its ordinary mutations. Emergency kill retains its existing lifecycle checks. Corrupt or unreadable durable control state still fails startup closed.

The supervisor does not infer success from `Running + target release`. A matching already-terminal release transaction can close only the exact transaction-to-intent crash cut after checking grant, transition, source/target and Fleet release-state bindings.

### 3.1 Inspect the current owner observations

Query `Health`, `Snapshot`, `ProductionMutationStatus` and `ReleaseSelection` through the current supervisord control socket. Record the exact Agent identity, control fence, lifecycle generation, grant digest, intent digest, release-transaction digest, observed immutable release bytes and daemon authority epoch. The affected process is fenced or absent; a requested kill does not itself prove exit.

The legacy `hepta-supervisor-intent-recovery inspect` command can display a persisted intent. Its digest-only `abort` directive is not an independently signed recovery decision and does not terminalize an ambiguous intent in the current owner path. Publishing a matching legacy directive must leave `recovery_required`, the quarantine and the ordinary-mutation fence intact.

### 3.2 Obtain an independent recovery decision

An authorized external signer supplies a `ProductionRecoveryDecision`. The decision binds:

- the Agent, original grant, current intent and current release transaction;
- the observed release and its manifest, Agentd and optional Matrixd program digests;
- the current lifecycle generation and daemon authority epoch;
- the signer identity/epoch, validity interval and requested terminal outcome.

The decision cannot select or move a release. It can terminalize only an already observed durable source/target outcome. An upgrade may recover as `committed` at its target or `rolled_back` at its source; a rollback may recover only as `rolled_back` at its target. A matching digest alone does not supply signing authority.

### 3.3 Submit and verify the terminal state

Submit the current control fence and signed decision through `ResolveProductionRecovery`. The daemon requires the `production-authority` build feature and an externally pinned verifier. The owner revalidates the fence, unresolved intent and transaction, fenced-or-absent process, observed immutable release binding, current Fleet admission frontier, signature, signer epoch and validity interval before terminalization.

Re-query the production-mutation and release-selection records after the response. A rejected, unavailable or indeterminate result does not establish terminality; preserve the durable records and reconcile the observed state before any further action. Do not delete the intent, lease or transaction to make readiness pass. These repository protocols do not themselves provide external signer custody, deployment qualification or operator acceptance.

## 4. Crash-consistency qualification matrix

The following are required target-host tests. Source/unit tests are not substitutes for receipts from this matrix.

| Fault point | Required invariant after restart/recovery |
| --- | --- |
| after `Prepared` intent publication | the Agent remains quarantined; status/recovery remains reachable when durable state is readable; request outcome is not reported as a safe rejection |
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
- `tests/signed_intent_recovery.rs` for queryable unresolved intent, preserved quarantine and rejection of exact-digest unsigned abort as terminal authority;
- the real-socket daemon recovery test for not-ready health, isolated Agent state and an unchanged control fence/intent after ordinary mutation is rejected;
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
