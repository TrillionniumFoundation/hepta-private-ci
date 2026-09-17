# Supervisor recovery and crash qualification

This document is the executable qualification plan for crash consistency, automatic restart, signed lifecycle recovery, and daemon scheduling in `codex-hepta-supervisor`.

It does **not** establish deployment qualification, independent operational acceptance, activation, or release. Source tests prove only the exact failure boundary that they execute. Host/process-manager SIGKILL evidence remains an external gate.

## 1. Invariants

The supervisor must preserve all of the following after any local failure boundary:

1. a stale process generation cannot advance lifecycle or release state;
2. an unresolved process lease is never treated as proof of liveness;
3. a signed production grant is never reported as a safe rejection after its durable intent was published;
4. an unresolved signed intent freezes ordinary mutations until an explicit recovery ceremony reaches a terminal journal state;
5. recovery never infers user-task success or release-selection authority from process liveness;
6. automatic restart is exponentially delayed and bounded to three attempts per five-minute pilot recovery window;
7. explicit operator drain/stop/kill/restart cancels pending automatic restart;
8. one fleet tick does not hold the daemon supervisor mutex across all managed Agents.

## 2. Repository-controlled crash matrix

| Boundary | Expected recovery | Repository evidence |
| --- | --- | --- |
| corrupt/truncated signed intent | fail closed; ordinary mutations unavailable | `signed_intent::tests::truncated_or_tampered_intent_fails_closed` |
| durable `Prepared` / `Queued` intent before daemon restart | daemon can serve read-only recovery state; `health.ready=false`; ordinary mutations frozen | `daemon::tests::unresolved_signed_intent_enters_recovery_mode_instead_of_fail_stuck` plus supervisor signed-intent recovery tests |
| signed mutation error after intent publication | caller receives `operation_indeterminate` | `daemon::tests::any_failure_after_mutation_start_is_indeterminate` |
| ambiguous signed intent with contradictory durable release lineage | construction remains fail-closed; no inference from matching target alone | existing `supervisor_tests::signed_intent_recovery_does_not_infer_commit_from_matching_target_only` |
| signed recovery request with stale fence or wrong intent digest | pure rejection before recovery mutation | `daemon_protocol::tests::signed_intent_recovery_request_binds_fence_digest_and_resolution` plus fence/digest checks in `signed_recovery.rs` |
| recovery with child/runtime/lease still present | reject recovery; no new process effect | checks in `signed_recovery.rs`; host-level process/lease teardown remains to be exercised on selected host |
| process identity/PID reuse at adoption | reject unless exact incarnation handshake proves identity | Unix driver exact-adoption tests and `unix.rs` process-incarnation checks |
| process lease mismatch/corruption | reject/fence instead of adopting as current generation | supervisor recovery and lease tests |
| startup health timeout | transition failed, stop child, schedule bounded automatic restart | lifecycle tests plus shared restart scheduler tests |
| unexpected running-process exit | terminalize exact generation and schedule bounded automatic restart | `tick.rs` plus shared restart scheduler tests |
| Matrix health/exit flapping | bounded exponential retry, fixed attempt budget, then stop automatic recovery | shared restart scheduler plus Matrix lifecycle tests |
| explicit operator stop/drain/kill/restart during pending retry | pending automatic retry is cleared | `control.rs`; lifecycle regression tests must preserve explicit action precedence |
| fleet periodic tick | mutex released between Agent slots | `daemon_tick::tests::sliced_tick_touches_only_the_selected_slot` and daemon sliced ticker |

## 3. Mandatory selected-host fault injection

The following evidence cannot honestly be manufactured by a source-only PR. The selected deployment host must execute these cases against the exact built `hepta-supervisord` binary and archive the command, binary digest, host identity, timestamps, exit status, logs, and post-restart state:

- SIGKILL supervisord immediately after signed intent file fsync and before release-state mutation;
- SIGKILL immediately after process spawn and before/after lease publication;
- SIGKILL immediately before and after release-state compare-and-transition/CAS;
- SIGKILL after target becomes healthy but before signed intent reaches `Committed`;
- kill/drain timeout with a child that ignores graceful signals;
- PID reuse/adoption attempt with mismatched process incarnation;
- disk full / `ENOSPC` while publishing the temporary intent and while replacing the final intent;
- fsync/rename failure for the signed-intent parent directory / durable replacement primitive;
- corrupt and truncated process lease plus signed-intent files;
- repeated crash loop until the third automatic restart is consumed, then proof that a fourth automatic start is not attempted in the recovery window;
- 256 registered Agents with one deliberately slow process driver, measuring snapshot/control latency for an unrelated Agent.

A test harness may use disposable children and private temporary fleet roots. It must not control unrelated host services, elevate privileges, or treat simulated time/fake process handles as selected-host evidence.

## 4. HOL / capacity acceptance

The daemon now obtains the supervisor lock separately for each Agent tick and yields between slots. This removes the previous whole-fleet critical section. It does **not** make one Agent tick asynchronous: registry/filesystem/process-driver work inside one selected Agent can still hold the mutex for that slice.

Selected-host qualification therefore records, for 1, 64, 128, and 256 Agents:

- p50/p95/p99 `snapshot` latency while ticker is active;
- p50/p95/p99 lifecycle mutation admission latency;
- maximum single-Agent tick duration;
- full-fleet tick cycle duration;
- observed fault count and missed tick count;
- the latency impact of one deliberately slow/unresponsive child.

No production SLO is claimed until a host profile names the threshold and exact measurements satisfy it.

## 5. Release-selection authority boundary

`runtime.supervisor` owns release **transition**, not candidate generation, evaluation, or independent selection. The signed production mutation path consumes an externally verifiable grant and binds it to the exact Agent, source/target release, control revision, lifecycle generation, authority epoch, and H7 evidence envelope.

Repository source can prove that an independently supplied decision is checked and consumed. It cannot prove that a production selector exists, is independently operated, or is accepted by an operator. `productionImplementation`, product composition, activation, independent acceptance, and release therefore remain false until those external composition/evidence gates are satisfied.

## 6. Commands

From `codex-rs`:

```text
just test -p codex-hepta-supervisor --lib
just test -p codex-hepta-supervisor
```

Strict lint/build and exact-head/merge-candidate receipts remain governed by the repository's existing CI entry points. A command written here is not a stored execution receipt.
