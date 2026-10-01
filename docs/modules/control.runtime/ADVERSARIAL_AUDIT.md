# control.runtime adversarial audit

Review date: 2026-10-01

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
| macOS release installation rejects a frozen staging rename | P1 integration availability | Rolling-upgrade cases fail during initial immutable release installation | Rename the complete directory on macOS before freezing and syncing its final path; catalog resolution continues to reject writable publication; extend the readonly-source regression and run all 41 Fleet cases |
| Test waits treat durable writes as latency guarantees | P2 fixture reliability | Browser revocation and cancellation admission/drain use one- or two-second waits; failures persist with two test threads on the busy host | Keep the early fence and in-flight cancellation assertions; bound the final durable fixture observations by 30 seconds without changing production limits |
| First log creation lacks a parent-directory durability barrier | P1 durability portability, source review | Core open creates the log after its existing directory sync; append synchronizes the file but did not explicitly persist the new directory entry | Sync the opened log and parent directory before returning the writable owner; retain the crash-after-sync recovery test and target-host qualification obligation |
| macOS crash recovery is blocked by a legacy PID token | P1 durable recovery | Source and fixed-base merge jobs pass Agentd but all three PlannerStore process-exit/recovery cases fail with `CorruptLock`; non-Linux token format does not match its parser | Use persistent kernel locks in the core, retain the destination lock through restore/open, and verify stale diagnostics, contention and stable lock inode across release; exact updated-host qualification remains required |
| Leaf terminal-cell integration root still uses a macOS alias | P2 qualification reliability | Later source-head qualification passes rolling upgrade then rejects the uncanonicalized terminal-cell cognitive root | Canonicalize the actual temporary fleet root before opening either cognitive owner; retain the production symlink fence |
| Missing-host rejection is absent from the final empty-ledger check | P2 admission regression coverage | Missing-host admission runs on a second owner but the final empty-ledger assertion observes only the original owner; duplicate setup also hits the 60-second watchdog during I/O pressure | Temporarily remove and restore the original host in one fixture; all rejected requests now share the final empty-ledger assertion and watchdogs stay unchanged |
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
Control/NDU all-target strict lint, all 41 Fleet cases, Fleet all-target strict lint, four-package all-target compilation,
40 module technical documents and source-navigation bindings, 40 canonical
regression bindings, Lane-D semantic
verification and its 18 self-tests, and eight workflow-command regressions.
The first full Agentd run completed with 196 passed (nine flaky retries), four
failed and ten timed out, with six skipped. The second full run with two test
threads completed with 208 passed (one flaky retry), one browser-fixture failure
and one historical-learning timeout, with six skipped. After the durable fixture
wait corrections, both focused cases passed (168 skipped). The timed-out history
case passed a separate retry in 4.35 seconds (169 skipped). Those narrower results
are not a full exact-head package pass. Local Agentd case fanout is now limited to
two without changing per-case concurrency or watchdogs.

The latest cross-platform candidate jobs are tracked separately in the PR record.
Targeted Agentd execution of the earlier affected path fixtures passed 15 cases
and skipped 155 others. Candidate qualification also includes the Fleet package
and its all-target formatting/check/lint after the release-installation correction.

The earlier three-package all-target strict Clippy run failed on NDU fixture helpers
(corrected by this follow-up) and 14 Agentd library diagnostics outside the control
final-use path. Those diagnostics cover unused browser/plasticity/learning
members, large automation/intelligence enum variants, cognitive/plasticity
argument counts and a collapsible cognitive-context conditional. Required
`just fix` completed but retained warnings; its exit status is not a strict-lint
pass. Automatic formatting outside this work's scope is excluded from the patch.
The full Agentd strict gate remains enforced; no lint level or maturity stage is
relaxed to obtain a successful candidate result.
The complete four-package strict command was rerun on committed source
148ec11b4da111083045c8674afa559457918896, tree
8b637707ba553bbbad631b2963752f6e12911ace, with a clean tree before and after.
It returned 101 with the same 14 Agentd library diagnostics; later test-target lint
is not certified by an early library failure. The staged plasticity submission
methods have callers only in lifetime tests. Their non-test source boundary is
not an upstream production learning trigger, consistent with the explicit gap in
learning.plasticity/CURRENT_IMPLEMENTATION.md.

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

The `940d651...` macOS source job passed the AuthBus and cognitive integration
binaries after the short-root corrections. It then failed both rolling-upgrade
cases during initial release installation and failed NDU owner-test helper lint.
All-target compilation passed. These are failed candidate records; the newer
publication and helper corrections still require their own macOS receipt.

## Additional immutable candidate evidence

The 148ec11 source job on macOS in run 36802270911 passed all 170 Agentd
unit cases, AuthBus and cognitive integration, and both rolling-upgrade cases.
The later terminal-cell binary failed one case on its noncanonical cognitive root.
The actual recorded package command returned 101 with 207 passed and one failed,
and did not reach Control/NDU/Fleet package suites. Four-package formatting and
all-target compilation returned zero. Strict lint returned 101 with the same 14
Agentd library diagnostics. Final job aggregation failed. These exact failed
command records remain failed evidence after the leaf fixture correction.

The additional complete local Agentd run at 148ec11 finished with 189 passed
(28 slow and three flaky retries), one failed, 20 timed out and six skipped;
command exit 100. Its source commit/tree and clean checkout matched before and
after execution. The failed storage-rejection observation remained Starting and
unhealthy rather than reaching the expected rejection/fence. This is failed
evidence, not proof that an invalid configuration served a request. During that run,
/proc/pressure/io reported full avg10=49.27; one admission fixture timed out
twice at the unchanged 60-second watchdog while several SQLite fixture cases
completed in 35–50 seconds. I/O pressure coincides with the failures but is not
a proof of every cause and does not convert them to pass receipts.

The 6ad983 source and fixed-base merge jobs on macOS in run 36805066541
both passed every ordinary Agentd binary (210 cases, six ignored), including the
one-owner admission and canonical terminal-cell fixtures, plus 154 Control unit
cases and eight Control integration cases. All three process-recovery cases then
failed with CorruptLock: package command exit 101, 372 passed and three failed.
The merge tree matched the source tree. Formatting and all-target compilation
returned zero; strict lint failed the same 14 Agentd library diagnostics. Fleet
and NDU suites were not reached. The legacy core token writer/parser mismatch is
a real crash-recovery defect, independent of the local Agentd pressure failures.
The correction replaces token liveness with a kernel lock and keeps its inode;
restore acquires it before replacement and transfers it into the opened store.
The stale-diagnostic/contending-writer regression now runs on every target.
These failed candidate records are not overwritten by the correction.

## Source-navigation correction

The broader document verifier also found dependent module observations predating
this candidate's source/build inputs, and six maps anchored on parallel commits
that were not ancestors of the selected branch. The original commit/tree pairs
were fetched and checked against Git objects. With every generic execution,
acceptance, activation and release claim false, those six source-navigation maps
were explicitly rebound to the selected committed source rather than treating
parallel-branch provenance as current qualification. Closed-world caller bindings
and mapped paths were validated; all existing completion/claim/gate fields were
preserved. Other affected valid-ancestor observations were refreshed separately.
The original records remain reviewable in Git history. This correction records
what source exists and does not certify execution or independent acceptance.
