# C2 terminal verification preparation and recovery closure

This appendix preserves new preparation and verification after the scratch
loss. It does not give the unavailable original preparation files new test
credit. The mathematical and scientific limits in
[CURRENT.md](../../CURRENT.md) remain in force.

## Observed state and execution boundary

The last complete archived epoch observation is still the original v8 record
at **2026-11-10 23:49:03 UTC**: three producer terminal reports and three active
fits. A later valid whole-job status request, **00:25:25.440--00:25:38.584 UTC
on November 11**, reported the same original durable C2 job running. That
response has no native sample timestamp, so this is its read span. The fully read command
journal ending at **00:33:29 UTC** contained three terminal records. Those
historical observations do not establish the current state of the other fits.

Subsequent C2 status, v9 observer-result and host-health calls returned
`MCP -32603 Internal error`. The two v9 launch requests used the same exact
request and idempotency key; their outcome remains unknown. No replacement
observer, training restart, new learning rate, new seed, changed physics or
reassigned fit budget was launched. The original request and every retained
response are in the [control follow-up](control-followup/COPY_LIST.json) and
later [01:10 read-only error record](control-0110/COPY_LIST.json). The next
status/result read, **01:30:42.885--01:30:44.341 UTC**, returned the same two
internal errors, preserved in its [original records](control-0130/COPY_LIST.json).
No further health call or launch was made in that observation. Native state
was unknown at that read.

A later read at **01:50:50.391--01:50:52.855 UTC** recovered the original job's
running status with the same ExecMainPID and InvocationID. Its entire
24917-byte command journal was read at **01:52:00.712--01:52:05.137 UTC**;
the version and contents are unchanged, with three producer terminal rows.
The journal does not establish each remaining child process's liveness.
These are later observations of the original execution, not a new job or a
substitute all-six terminal barrier.
The [source-bound records](control-0150/COPY_LIST.json) retain all original
responses, the complete journal and the later epoch nodes.

The controller's final RESULT was still absent in the 01:53 read. At
**01:55:09.609--01:55:17.790 UTC**, three small immutable commit records were
read and checked by SHA. Their producer-reported complete epochs and strict
best D values are:

| Seed / learning rate | Latest complete epoch | Strict best D macro-F1 | Best epoch | Stale count |
| --- | ---: | ---: | ---: | ---: |
| 101 / .001 | 105 | .33807429871203515 | 104 | 1 |
| 211 / .001 | 104 | .3432623604823944 | 104 | 0 |
| 307 / .001 | 105 | .319200972102104 | 103 | 2 |

These nodes do not provide independent checkpoint replay, a terminal record
or a new learning-rate selection. Their cumulative process-wall prefixes
belong to the latest complete epochs, not necessarily the selected best
epochs or a first target crossing. They are not complete final wrapper bills.

No actual terminal input assembly, independent C2 terminal audit, longer C2
resource analysis or rendering has been executed by the preparation archived
here. Subject E remains outside these programs. All execution templates are
disabled. An actual run requires all six original candidate terminals, the
controller's immutable `completed_attempt_roster` result, complete durable
native logs, source/input identities and process-termination observations.

## What this preparation makes reviewable

| Component | Exact role | Preserved limits and scope |
| --- | --- | --- |
| Terminal bootstrap v3 | Assemble source-bound terminal records, then run the unchanged independent auditor under an actual OS observer | Assembly 120 s / 256 MiB; audit core 1800 s / 2 GiB; native wrapper 1950 s; one worker and thread |
| Resource analysis v2 | Read finalized metadata and retain every original opportunity cost | Core 120 s / 512 MiB; no model, optimizer, forward, backward or oracle calls |
| Complete OS supervisor | Measure the full resource-analysis child through its real `wait4`, including receipt serialization and exit | Core 120 s; startup 5 s; finalization 30 s; native wrapper 155 s |
| Renderer | Consume finalized resource tables and their complete envelopes without selecting rates or recomputing statistics | A separately bound rendering authorization; unchanged old budget files |
| Independent reviews | Check source contracts and cost arithmetic against exact snapshots | Static review and software fixtures have their own explicit scope; neither is actual C2 replay |

The unchanged terminal auditor capsule remains SHA256
`87bedabde7f37ec8d70a80305691f1116e80493174a5cd33bf7058f635230b3a`.
Its source, twenty-eight original synthetic tests and plan remain in the
[earlier preparation](../p0p5-c2-progress-20261110/terminal-auditor/PLAN.json).
Those tests have not been run as the native preflight for an actual C2 audit.
The new [bootstrap preparation](terminal-bootstrap/program/README.md) records
its own exact sources and tests. The v2 broad check has 21 tests on its own
source; the v3 change has four targeted checks on the later source. These are
distinct executions and are not reported as a rerun of all 25 tests on v3.

The v3 timing correction passes the original setup deadline into the actual
process observer. Setup time ends at the recorded `Popen` boundary. A missing
or late process start cannot receive a successful setup record. The audit's
1800-second allowance is unchanged. The separately measured native wrapper
must still finish within 1950 seconds; unused setup time never enlarges the
audit core allowance.

The resource-analysis reconstruction explicitly preserves the missing v1
source inventory. New implementation stages, failed software attempts,
corrected attempts, source snapshots and validation costs are retained
separately. It cannot borrow the lost original v1 test receipts.

The final new core has **52 passing tests on its exact frozen source**,
manifest SHA256
`f2d1ce683591a9b8575aab2d0981bf67b9e465bf9686a8da2e87a2246a0ea70e`.
Its [preparation summary](resource-core/SUMMARY.json) and
[attempt ledger](resource-core/ATTEMPTS.json) preserve eleven owner validation
attempts, including the failed first integration fixture. An independently
constructed three-case contradiction set exposed missing native CPU/wall/PID
consistency checks in the earlier H1 source. The corrected H2 source rejects
all three and retains the positive case. The old passing H1 tests and the
later counterexamples both remain in the record. These metadata fixtures
do not constitute an actual resource analysis or a model result.

The complete OS supervisor changes exactly one manifest literal from its
recovered v2 source. The [independent source review](supervisor/review/RESULT.json)
checks that the rest of its syntax tree and the process helper are unchanged,
including the 120-second core, 5-second startup, 30-second finalization and
155-second native limits. Its new source was compiled, but the complete
supervisor authorization/artifact path was not functionally executed here.

The [renderer](renderer/program/README.md) retains its original chart-making
main program and adds a source-bound consumer for the resource analysis's complete **155-second
native envelope**. Checking only the 120-second child receipt is insufficient.
Its new gate consumes the original request, acknowledgement, complete logs,
durable terminal and GNU time together with the exact supervisor and resource
sources. It binds the actual 18-argument native request to the observed core
command and checks wall/CPU containment. Eight pure-JSON owner tests pass on
the final candidate. No chart, Matplotlib process, C2 data or model was used
in those tests. The source's own receipt and independent review retain the
earlier candidate and any failed validation records separately.
The independent closure's first source check enumerated nine files before
the probes but only seven afterward, recording `source_unchanged:false`.
That original driver and receipt remain intact. A separate read-only complete
roster check found all nine hashes unchanged without repeating the probes.
The [independent review](renderer/independent-review/REVIEW.json) preserves
both the coverage error and the bounded correction.

## Native evidence is checked from its original records

The native envelope binds the exact launch request, acknowledgement, durable
terminal, complete ordered stdout/stderr pages, GNU time output, bootstrap
authorization and source files, bootstrap receipt and complete core OS
receipt. The [retained operator examples](operator-schema/COPY_LIST.json)
document the actual response shapes. Their existing observation jobs are
schema examples and do not stand in for the future auditor job.

The log parser requires contiguous byte offsets, exact hex-decoded lengths,
complete EOF, matching job identity, no truncation and durable publication.
GNU time's complete wrapper measurement and the precise core `wait4`
measurement are checked separately. Printed GNU elapsed time is treated at
centisecond resolution and receives a conservative 0.01-second allowance
before comparison with the fixed wrapper cap.

A same-key reconciliation after a lost acknowledgement is recorded as a
transport event. It needs the original exact request and the original
dispatch response or error, followed by the acknowledgement of the same job.
It does not grant a second execution. A changed request, changed key,
unbound response, unknown terminal or incomplete log leaves the result
unadmitted. Costs for control calls and native execution retain their original
scopes.

The OS observer checks real process identities, descendants that changed
their process group, adopted children, unknown CPU and final process scans.
An adopted child is not silently counted as fully measured direct-child CPU.
The new tiny-process validation has new source and receipts; it does not
reconstruct the unavailable old twelve-test validation. Its
[nine checks](os-helper-validation/SUMMARY.json) pass on the exact recovered
helper: eight actual tiny Python child fixtures and an expired-deadline case
that prevents launch. Timeout, RSS, a new-session descendant, an adopted orphan,
unreadable process evidence and an independently cleaned residual are covered.
The guard's wall and CPU values are explicitly prefixes; the waited worker CPU
includes reaped fixture children. Neither is silently expanded to an exact
complete outer native cost. These checks do not qualify the entire supervisor.

## Resource accounting and comparison remain fixed

The independent [training-side static review](training-review/RESOURCE-REVIEW.json)
checks the cost and selection implementation against the saved source:

- All six opportunities per temporal core remain in the bill, including
  failed candidates and already consumed partial updates.
- A quality observation uses the original complete parent cost plus its
  observed child-training prefix. The final bill also includes the complete
  continuation wrapper. Unobserved wrapper time is not distributed
  retrospectively across earlier quality points.
- Strict best-checkpoint selection and the `0.002` plateau improvement rule
  remain separate. The common HCSN learning rate needs all six independent
  quality verifications; an adequately trained comparison additionally needs
  all three selected seeds to satisfy independent adequacy.
- The existing 300/900/1800-second resource view is copied byte for byte.
  The later continuation view does not alter or reselect those results.
- The target is the first **recorded complete epoch** at development macro-F1
  0.30. No step-level interpolation is invented. A three-seed median is
  reported only when all three crossings were observed.
- Missing CPU components stay unknown or a lower bound. Process RSS is not
  GPU memory or memory measured at the exact target crossing. Energy and
  billed currency remain unknown.

Static review does not supply missing terminal data, fresh development
predictions, training adequacy or numerical qualification. The previous
finite-tail, phase, short-gap, log-risk and posterior-coverage limitations
remain unchanged.

## Exact publication and hosted verification

The [verification originals](verification/ORIGINALS.zip) retain the new local
checks, remote-object readback, publication records and hosted science
artifact. They concern the previously published recovery head
`9f16aa325b12004ddc0d9fa325fdc67531d027fc`, tree
`92f8647353bd34a194b94fde015428641e3549e4`.

A new filtered Git clone, without local object seeding or alternates, read
all **87 changed regular files** and checked their complete byte counts,
SHA256 hashes and Git blob identities. Its complete verification child used
521.955562111 seconds wall time and 25.757144 seconds waited CPU. This is an
archival verification cost, not model-training time.

The local corrected integrity check passed **12 manifests, 21 Markdown
documents, 1664 evidence files, 106 direct ZIP archives and 479 links**. The
committed-object check separately verified 1667 regular evidence/extra files
and twelve manifest identities. The original failed two-link check and its
append-only correction remain in the preceding recovery appendix.

Hosted science run
[42933021590, attempt 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42933021590)
tested merge commit `d96e66a23f4608133827df43d8ec127d98bad681`, with the same
source tree as the recovery head. The original artifact is 127296 bytes,
SHA256 `49cb833e09538f7afcf605bd947251627285098493ccfefbdf4f5f4a463a4f52`.
All fourteen members were read and checked. All 42 recorded qualification
source files were verified against the then-local bytes of the recorded
9f16 source tree. Later CURRENT edits are outside that equality claim. The
artifact records:

- 92 qualification tests, with zero failures, errors, skips or expected
  failures, and unchanged source;
- the four declared fixed-policy error-budget fixtures passing;
- the same 1664-file / 106-archive / 479-link evidence check passing;
- the independent finite DP/QVI fixture and memory-control semantics checks
  completing successfully.

The qualification worker reports 16.206551975 seconds wall time and
16.192777844 seconds process CPU, with its original prefix scope. This does
not measure all CI setup, installation, billing or workflow time. The new
local artifact retrieval child used 0.361050080 seconds wall time and
0.115891 seconds waited CPU; no tests or scientific computations were rerun
by that retrieval.

The repository-wide blocking workflow and the HCSN science workflow remain
separate. The later retained [blocking-run response](ci-blocking/blocking-run-raw.json)
and [first jobs page](ci-blocking/blocking-jobs-first-page-raw.json) identify
run 42933021807 on the recovery head. That page includes failed contract,
Windows and cargo-deny jobs while the overall run is still in progress.
Only the first page was retrieved; these are not an exhaustive job census or
a diagnosis of those failures. A fixture pass does not confer trained-state numerical accuracy,
real-task scientific benefit, repository-wide success or permission to
advance to scale and hardware optimization. This appendix also gives no CI
credit to a later source tree that was not tested by the recorded run.

## Evidence retention

Each copied original is bound by this appendix's manifest. Program capsules
have their own member manifests. Raw error responses, failed software
attempts, original and corrected source versions, missing-file inventories
and scoped cost receipts are retained. Nested cost records are not added to
their enclosing native or verification measurements.

The actual next step remains the all-six terminal barrier followed by one
bounded independent audit. The restored interface reports the original job
running, and the complete journal has only three producer terminals. Until
the required all-six barrier is established, the prepared execution remains
disabled and the scientific status remains **HOLD**.
