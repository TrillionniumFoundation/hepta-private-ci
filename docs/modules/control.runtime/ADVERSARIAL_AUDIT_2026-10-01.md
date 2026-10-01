# control.runtime adversarial audit — 2026-10-01

## Source and review scope

The review uses the latest default-branch development plan, `docs/DEVELOPMENT.md`
v8.0.0 (2026-09-23), at base
`a126987b84737dbc2ee2592442a314117bddb4a2`. Implementation work is isolated on
`codex/control-runtime-convergence-v1`, draft PR #1164. The review includes the
public control-plane facade, its bounded planner, journal/store, execution and
recovery state machine, organ host, Agentd final-use callsite, and NDU admission
boundary. Public wrappers, callers and reopen behavior are reviewed together;
private legacy helpers alone do not describe the exposed contract.

Candidate SHA/tree, fixed-base merge identity and command results belong in the
workflow artifacts and PR validation record. Earlier passing checks do not qualify
a later commit. This report does not advance `CURRENT_STATE.json`.

## Documentation assessment

Detailed technical development documentation exists. `TECHNICAL.md` contains 17
sections covering mission, ownership, source bindings, contracts, state, failure
behavior, testing, integration, compatibility and completion criteria. The module
execution dossier and implementation map provide source and regression navigation.
The execution/convergence guides specify staged delivery. `PENDING_RECOVERY.md`
now describes the implemented bounded driver, exact request resolver, original
grant binding, first-observation transition and unresolved product composition.
`CURRENT_STATE.json` and `STATUS_MODEL.md` distinguish source, composition,
qualification, independent acceptance and activation.

Documentation is sufficient to implement and review the present library
contracts. It is not yet a complete operational runbook for a production recovery
controller: that controller, its real request ledger/effect adapter, named host
qualification, backoff/retention policy and independent anchor owner remain to be
composed and measured. The design's presence must not be read as their delivery.

## Placement and completion assessment

Control selects a bounded feasible plan from coherent snapshots and remains off
local hot paths. NDU evaluates utility; the independent authority owner validates
final-payload-bound grants; the effect owner executes or observes effects. Plans,
pending projections and fanout continuations remain `DENY_ALL`. Moving effect
ownership or durable facts into the planner would weaken this separation.

All six subsystems have design, source and guarded public entries. The canonical
product-callsite assessment is:

| Subsystem | Product callsite integrated | Remaining completion boundary |
| --- | --- | --- |
| Bounded planner | Yes | Current exact-candidate qualification and operational evidence |
| Authenticated Agentd final use | Yes | Read-only final use; no global effect execution claim |
| Planner journal | No | Named product caller and durable fact/anchor ownership |
| Planner store | No | Product retention, backup/recovery and selected-host exercises |
| Authority execution/recovery loop | No | Exact request ledger, real effect adapter and bounded scheduler |
| Trusted organ host | No | Named product composition, retry owner and downstream idempotency |

Exact-source, fixed-merge, target-host recovery, independent acceptance,
activation and release stages remain false. There is no defensible single
completion percentage: the library protections and two callsites are materially
present while the global durable effect product is still uncomposed.

## Reproduced findings and corrections

| Finding | Severity | Before | Correction and regression boundary |
| --- | --- | --- | --- |
| Bare dispatch claim cannot survive reconciliation and a second reopen | P1 recovery correctness | First reconciliation wrote a reconciliation frame without an initial observation; reopening rejected the journal | Persist the first queried observation as a terminal frame, then use reconciliation frames for subsequent indeterminate observations; cover v2, legacy v1, second reopen, conclusive replay and zero redispatch |
| Conclusive public reconciliation ignores supplied original grant | P2 binding integrity | Existing-terminal fast return accepted a mismatched grant | Verify the original durable grant before the fast return; assert no mutation or effect-owner call on mismatch |
| NDU candidate union admitted beyond the shared bound | P2 resource admission | Individually bounded evaluated/rejected lists could exceed the shared 128-candidate budget | Reject the union and oversized Pareto input before sorting/index allocation; cover 128 accepted and 129 rejected |
| macOS temporary roots invalidate product tests | P2 qualification reliability | Long Unix-socket roots and noncanonical checkpoint parents hid later integration results | Use short, canonical, isolated fixture roots; preserve production socket-length and symlink validation |
| Named-host program and test-helper lint failures | P2 qualification reliability | Overflow probe panicked; manual ceiling division and helper `expect` calls violated strict lint | Return an explicit qualification error, use `div_ceil`, and make fixture setup failures explicit without suppressing production lint |
| Stale source anchors omit new recovery tests | P2 documentation traceability | The implementation map referenced a new controller regression absent at its historical source anchor; NDU observations also predated the fixes | Rebind the control and NDU maps to actual committed source/tree and refresh exact source objects while preserving every maturity and external-evidence field |
| Successful displayed CI step can conceal failure | P1 evidence integrity | `continue-on-error` conclusions could be mistaken for pass receipts | Assess command exit/status, actual outcome and final fail-closed aggregation; document that a passing unit binary does not certify later integration binaries |

The interrupted-dispatch case was reproduced failing before the correction and
passing after it. The controller regression queries the effect owner twice across
an indeterminate then conclusive observation and dispatches zero times.

The review also checks existing guards for exact snapshots, owner ages, resource
axes, duplicate final payload identities, immutable conclusive receipts, canonical
record checksums/transitions, store limits, exclusive process ownership, uncertain
write poisoning, compaction evidence preservation, independently bound backups,
generation fencing and complete organ fanout evidence. A trusted synchronous
in-process handler can still block; the organ host is not a sandbox or an effect
executor. Continuations refuse incomplete delivered evidence and do not authorize
retry by themselves.

## Qualification evidence and remaining blockers

Completed local checks include 170 control-plane cases (154 unit, 16 integration;
qualification failpoints enabled), all 74 NDU cases, 15 targeted Agentd cases,
NDU all-target strict lint, 40 canonical regression bindings, Lane-D semantic
verification and its 18 self-tests, and eight workflow-command regressions.
The first full Agentd run completed with 196 passed (nine flaky retries), four
failed and ten timed out, with six skipped. A second full run limits test threads
to two while preserving assertions, case inventory and watchdogs, to separate
resource contention from reproducible product failures. Its result and the latest
cross-platform candidate jobs are tracked separately in the PR record. Targeted Agentd execution
skips 155 other cases and must not be described as a full-package pass.

The three-package all-target strict Clippy run failed on NDU fixture helpers
(corrected by this follow-up) and 14 Agentd library diagnostics outside the control
final-use path. Those diagnostics cover unused browser/plasticity/learning
members, large automation/intelligence enum variants, cognitive/plasticity
argument counts and a collapsible cognitive-context conditional. Required
`just fix` completed but retained warnings; its exit status is not a strict-lint
pass. Automatic formatting outside this work's scope is excluded from the patch.
The full Agentd strict gate remains enforced; no lint level or maturity stage is
relaxed to obtain a successful candidate result.

The prior `2095284...` macOS source job is failed evidence: 170 Agentd unit cases
passed, the next AuthBus integration binary failed two path cases, all-target
compilation passed, and strict lint failed two NDU named-host cases. Later fixture
and program corrections require their own exact-head results. Step display
conclusions and inherited tests do not certify a full candidate.

## Optimization priorities and stopping boundary

1. Compose the existing bounded pending driver with the original request ledger,
   effect-owner observation port, fair scheduling/backoff and shutdown policy.
   Missing requests, timeout and `NotFound` remain unresolved; none permit replay.
2. Assign independent checkpoint/backup anchors and qualify disk-full, filesystem
   loss, rollback and sustained overload on the selected host. Define retention
   from measured pending age and reconciliation latency.
3. Compose organ fanout recovery with a separately bounded retry owner and target
   idempotency protocol. Retain the exact successful-prefix evidence independently.
4. Resolve the cross-module Agentd lint debt without removing unactivated
   interfaces or changing runtime authority merely to satisfy lint. Requalify the
   complete immutable source and fixed-base merge on Linux and macOS.
5. Obtain independent semantic review, operator acceptance and the respective
   activation/release evidence before advancing those stages.

The repair loop closes reproducible defects within the reviewed source boundary
and repeats affected checks when a new failure warrants them. It cannot establish
that no future optimization exists. Source review convergence, candidate
qualification and production completion are separate outcomes; the unresolved
composition and evidence items above remain explicit deliverables.
