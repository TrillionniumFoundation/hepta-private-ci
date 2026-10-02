# runtime.supervisor adversarial audit, 2026-10-02

## Scope and immutable baseline

Reviewed PR #1306 source `e00b7d2b6acccf6a35683a595cf88e1f23673642`,
stacked on `e8f8f2d0ca399b0a68abba4da90a3be5114d0735`.
Remote main observed at `c6f90d48c40f7b5267db587bb3c3f4934f1414a8`.
This review follows the current technical guide and actual lifecycle, driver,
Fleet, daemon and recovery consumers; it does not infer implementation from
source maps or transfer historical receipts to modified bytes.

Baseline native run [36960866551](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36960866551)
completed successfully for Ubuntu 24.04 and macOS 15 source-head/base-merge,
including the required aggregator. Baseline deep run
[36960866316](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36960866316)
passed both lanes. These executions cover e00b source only. They did not contain
the new deadline regression cases below.

Before publication, the candidate advanced through four linear descendants to
`ca7c978ac61b92ece1e61715d82667e9abd4876e`, tree
`8169a8d8f0604c093f8fca399af593d701a580a0`. That exact commit is the
continuation base for these repairs. Its only executable change handles
`ProcessLookupError` alongside `FileNotFoundError` in the procfs deadline-test
fixture; its workflow trigger, historical e00b observations and source-map
updates are preserved. The complete `codex-rs` tree is unchanged from e00b.

The two reviewed source repairs were replayed with identical Rust blobs.
The current implementation map retains all continuation-base source and
historical-observation fields, adding only the five reviewed operation test
references. Immutable bindings await the published source identity. Earlier
local test results below remain development observations of the original
reviewed bytes; they are not executions or qualification of this continuation
head, and the historical remote receipts remain bound to e00b.

On this continuation, the six Supervisor CI/status/receipt validator modules
passed all 73 cases. Five affected documentation/source-identity/deadline
fixture modules passed all 66 cases, including the procfs disappearance
fixture, with the repository's `scripts` import path supplied. The derived
projection check reported no drift. These checks do not replace the pending
immutable-source binding refresh or hosted native qualification. No native
Rust tests were rerun during this byte-identical source continuation.

## Concrete findings and repairs

### P1: failed Matrix Stop could run indefinitely

`matrix_tick.rs` computed a fresh `now + stop_grace` whenever an expired
AwaitingHealth/Unhealthy phase retried `request_stop`. A driver error preserved
the old phase but no intention/deadline. Repeated failures never reached Kill.
A later healthy observation could return the process to Running and erase the
reason to stop. The same missing intention affected `defer_agent_action_for_matrix`:
a failed companion Stop during a main Drain left the main deferred, while
ordinary ticks did not retry the admitted companion Stop.

The repair stores the first pending deadline inside the exact `MatrixRuntime`
owner and shares `matrix_control.rs` across watchdog and deferred-control
paths. Failed signals preserve the acknowledged phase; successful signals
alone emit Stop/Kill events. A replacement runtime is created with no inherited
pending intention. Stopping/Killing cannot publish healthy readiness.

### P1: failed Matrix observation suppressed already-due containment

An acknowledged Stopping deadline was evaluated after `poll`. Persistent poll
errors suppressed Kill forever. Initial health expiry likewise required a
successful poll, allowing an unobservable startup to exceed its readiness
budget indefinitely.

Independent review then found another original-source cut: a Running
companion with persistent poll errors never entered Unhealthy, so no grace
existed to expire. A new failing regression confirmed it. Both explicit
negative readiness and absent poll observations now share one Unhealthy
transition. Repeated failures retain that grace; valid health before Stop
recovers normally, and a later separate failure gets a fresh health budget.

Ticks now attempt already-admitted pending/due control before polling. An
expired health budget with a failed poll admits bounded owner-local Stop.
Signal and probe faults remain separate diagnostics. A failed signal cannot
hide an exact exit, and a stored exit still prevents any further signal/poll
while its original lease cleanup is retried.

### P1: failed main startup observation bypassed health timeout

The main's initial AwaitingHealth timeout was also behind fallible Fleet reads
and process polling. A fresh retained process could avoid both Stop and Kill
through persistent observation errors despite its expired health budget.

`tick_health.rs` admits one current-spawn Stop before fallible Failed-lifecycle
publication and retains its original grace. A current Fleet observation may
produce the exact Failed CAS; an unavailable observation permits only existing
owner containment and makes no lifecycle-CAS claim. Recovered health cannot
re-admit a process after this Stop intention. Existing same-spawn pending
controls, fenced owners and stored exits keep their stronger existing rules.

## Regression and verification observations

- Five deterministic Matrix regression tests failed on unmodified e00b
  production source. Their repaired focused suite, including the existing
  companion containment/order tests, passed 24/24
- A separate initial-main-health regression failed on the unmodified main
  watchdog. It passes after repair; two further tests cover unavailable Fleet
  and failed Stop followed by recovered health
- The final reviewed default library ran 433 tests: 417 passed, 16 failed,
  zero skipped. All sixteen failures report EPERM at local Unix-socket creation
  or the resulting unreachable fixture daemon. One reviewed execution
  escalation reproduced the same environment failure. No failing transport
  tests were skipped, replaced or weakened
- All ten newly added regression cases passed within that full library run
- The previous 94 current-repair library identities are preserved in order;
  ten new exact leaves are appended (104 current-repair requirements and
  134 total mandatory library identities, including the stable base). The Fleet
  inventory remains five. Validator tests additionally enforce the new source-file identities

The qualification-feature library ran 438 tests: 422 passed, the same sixteen
Unix-socket environment failures, zero skipped. The six CI/status/receipt
Python validator modules passed all 73 cases. These overlapping library runs
are not summed as distinct test coverage.

The additional Running-poll regression observed `(stops, kills, drops) =
(0, 0, 0)` before repair where bounded containment required `(1, 1, 0)`.
A separate source review found no further actionable issue in the edited
lifecycle paths after that repair; this is not independent operator acceptance.

Final scoped `just fix` and full `just fmt` completed successfully. Strict
package all-target Clippy with `--features qualification --no-deps -- -D warnings`
also passed after final formatting. Unrelated
formatter-only edits to 46 existing Python scripts were restored to preserve
scope. Changed Rust and Python files independently passed formatting checks;
this is not a repository-wide clean-format claim. No local native tests were
rerun after the final fix/format. Exact-head hosted qualification for the
published, finally bound source remains required; baseline CI success cannot
satisfy it.

## Other reviewed boundaries and remaining work

The audit traced Start/replacement admission through current Fleet catalog and
lifecycle checks; Stop/Kill/restart through durable intent and lineage;
main-before-companion emergency control; stored exact exits through lease
cleanup; constructor denial through independent owned-process acquisition;
signed transitions through journal/quarantine; daemon cancellation through its
single retained writer owner; Unix control through exact-peer bounded I/O;
and bounded read/diagnostic queues through their consumers. No additional
concrete failure was established in those inspected paths in this pass.

The module remains incomplete at documented system boundaries:

- Matrix/watchdog control intentions are same-owner only; durable operator
  main Stop/Kill does not establish all cross-daemon restart/watchdog deadlines
- Cross-daemon exit-cleanup witnesses, launch-before-lease reconciliation,
  complete predecessor/replacement lineage and atomic recovery observation
  remain separate implementation gaps
- Per-Agent parallel mutation ownership and measured target-host resource,
  scheduling and durability behavior remain unqualified
- Final-component file checks do not establish ancestor-directory ownership
  or the complete host permission model
- Exact deployed binaries, external authority custody/rotation, independent
  operational acceptance, activation and release remain unestablished

Baseline derived-diagnostics run
[36960866367](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36960866367)
failed before parity verification because automation.taskflow's canonical anchor
`41b2da214f5541da09e0313e7b8576add6ed3839` is not an ancestor of e00b.
That observed repository-wide provenance blocker is not relabeled as a runtime
failure or repaired by weakening the ancestry check. No global-green,
production-readiness, merge or deployment claim is made.

## Publication baseline refresh

Before publication the upstream candidate advanced to `75ea1a12b3bbc0c16d4c1ef28594cbcea917c545`. The two-commit change from ca7 only adds Fleet argument-name comments/formatting, the diagnostic source path and current source-map/report observations. The Supervisor Rust subtree is unchanged. These three unpublished repair commits were replayed onto that exact ancestor, preserving every reviewed Supervisor Rust blob and the new upstream map observations. Prior local execution remains scoped to those identical Supervisor bytes; this is not a new full candidate execution receipt. Fresh hosted checks remain required.
