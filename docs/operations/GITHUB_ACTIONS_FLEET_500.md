# GitHub Actions fleet: 500-job real test fanout

## What is implemented

- A default-off manually dispatched workflow:
  .github/workflows/github-actions-fleet-500.yml
- Source-only deterministic planner: scripts/github_actions_fleet_500.py
- Read-only GitHub API telemetry: scripts/github_actions_runner_audit.py
- Adversarial unit tests: scripts/test_github_actions_fleet_500.py
- Org-wide interval overlap proof: scripts/github_actions_org_capacity.py
  and scripts/test_github_actions_org_capacity.py

This machinery neither creates runner registrations nor purchases Larger
Runners. It does not cancel existing CI or bypass required checks.

## Verified baseline and limits (2026-10-16)

The public hepta-private-ci main commit
f8c9419df6ddeb36ff8b522a50219981fb8d9345 contained 76 Python test
files under scripts/, with 903 AST-defined test_* methods before adding
fleet tests. After adding nineteen planner, direct-fanout and org-peak regressions, 922 statically
recognizable unittest.TestCase methods were available in the local
source-only scan. Not all 922 were independently run. The planner selects
500 different method identifiers, not 500 fake sleeps or build duplicates.

Workflow runs are not jobs: GitHub can report a queued workflow with zero
jobs (historical example:
https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/35298977359).
Pending, queued, skipped and cancelled do not count toward observed
running-job throughput.

Per GitHub Actions limits, a single job matrix has a maximum of 256 entries.
A single 250-matrix workflow dispatch can use at most 250 job slots;
dispatch **two** pinned cohorts A and B to offer 500 unique jobs.
Actual simultaneous execution is limited by your account plan, runner group,
operating-system pool, budget, and other CI workloads. Standard GitHub-hosted
concurrency is 20/40/60/500 for Free/Pro/Team/Enterprise respectively.
**The organization plan was verified as Enterprise via Pocket4 authenticated GitHub CLI on 2026-10-17.** GitHub's published *default* Enterprise standard-hosted concurrency is 500, but a 500-job simultaneous running peak has not yet been observed or verified, and effective per-pool limits may vary.

A read-only 33-second scan of 30 active org repositories at 2026-10-17T04:08:16Z..04:08:49Z observed 102 job records in `in_progress` state across 33 workflow runs (Linux x64 28, ARM 22, Windows 32, macOS 20); the non-atomic scan is **not** a same-instant peak claim. Read-only billing reported net zero Actions compute for the sampled SKUs, with storage usage billed separately. These figures are sampled, not a future price guarantee.

The GitHub Actions workflow concurrency group uses `queue: max` (supported since May 2026) alongside `cancel-in-progress: false` to retain pending manual dispatch runs instead of replacing the previous pending cohort.

Reference: https://docs.github.com/en/actions/reference/limits
Usage: https://docs.github.com/en/actions/concepts/metrics

## Do the cheap audit first

After the workflow lands on the default branch, open GitHub Actions and
run "GitHub Actions fleet audit and real-test fanout":
mode=audit and execute=false. This creates only one capacity-audit job.
Its 7-day JSON artifact reports provider workflow-run counts separately
from sampled, actually running jobs, queue time, cancel outcomes and
old queued zero-job entries. Sampling is explicit; it does not represent
an organization-wide entitlement.

Org administrators can verify subscription, billing and organization-level
runner utilization in GitHub Settings and Insights -> Actions usage metrics.
An ordinary per-repository GITHUB_TOKEN cannot prove these org settings.

## No head-of-line planning Runner for real fanout

With \`execute=true\`, the real-test job uses a static GitHub-readable
matrix of 8/16/32/64/128/250 shard indexes; it has **no** \`needs: plan\`.
GitHub can enqueue the real jobs immediately, rather than making the
entire parallel wave wait for a single Ubuntu planning job to start.
An explicit runner choice selects `ubuntu-24.04`, `ubuntu-24.04-arm`,
or opt-in `ubuntu-slim` for Python tests, allowing controlled pool qualification.

Each job independently checks out and verifies the same complete source SHA,
selects one immutable real method through \`--execute --case-index\`, and
actually runs that method using Python unittest with original project
environment. Unsupported direct sizes, a wrong/missing SHA, an absent test,
a mismatched cohort or a bad index fail closed; preview still uses a cheap
\`execute=false\` planning job to compare manifest hashes.

The direct job set remains 250 per cohort (not 500 in one matrix) because
GitHub has a 256-entry matrix limit. Neither job count nor workflow queued
state demonstrates actual 500 Runner concurrency; use the organization
interval-overlap audit for that.

## Optional `ubuntu-slim` Python-only pilot (2026-10-18)

The direct-test runner selector now also accepts `ubuntu-slim`, a standard
GitHub-hosted Linux x64 container with one vCPU, 5 GiB RAM and a 15-minute
execution limit. The published image includes Python 3.12 and Git. This is
**opt-in**; `ubuntu-24.04` remains the default, and Bazel, Rust builds,
Windows/macOS jobs and release pipelines are unchanged.

The pull-request fleet selftest uses `ubuntu-slim` to validate checkout and
the Python regression suite before any wider manual pilot. Its standard-hosted
job count shares the organization's existing 500-job quota; switching labels
does not create extra capacity or guarantee faster admission.

When the selftest passes, compare pinned eight- or sixteen-shard disjoint
Python test slices on `ubuntu-slim` and `ubuntu-24.04` under actual queue
conditions. Verify strict receipts, job identity, queue-delay P50/P95, and
concurrent execution intervals. Do not add sleeps, artificial start barriers
or duplicate tests to inflate the concurrency metric.

## Preview, pilot and full dispatch

1. Merge/activate the workflow on the default branch. Choose one complete
   40-hex Git commit SHA S containing the actual code to be tested.
2. Run mode=fanout, cohort=A, per_cohort=250, source_sha=S,
   execute=false. Repeat for cohort=B. Both jobs merely compute artifact
   plans, with 250 distinct tests each. The full manifest SHA256 must match
   between cohorts. The source SHA must match too.
3. Run a cheap, pinned per_cohort=8 pilot on each cohort and check every
   Job log for successful real Python unittest completion before increasing.
4. After verifying quota, budget, pilot success, runner-pool availability
   and useful work, run both cohort A and cohort B with the same SHA S,
   per_cohort=250, execute=true. Their concurrency groups differ by cohort,
   so they can run simultaneously *if* there is provider capacity.
5. Verify real running Job IDs (not Workflow Runs), throughput, individual
   failures, queue times, and billed minutes. Do not interpret queue totals
   as capacity achieved.

Execution refuses an unpinned source SHA, invalid cohort, size outside
1..250, mismatched checkout, duplicate test method or shortage below
2*per_cohort real methods. Default execute=false avoids surprise bills.
All matrix jobs use the same checked commit. Each method is executed
with python3 -m unittest -v and failures propagate normally.

This only shards statically recognizable Python unittest methods; it is
not a replacement for existing Rust/native/merge-candidate CI or evidence
qualification. A method found in AST is not assumed to import or pass.
Continue optimization with real Nextest archive/shard evidence after
the pilot; consider cache deduplication and fair budgeting rather than
permanently burning 500 full-repository checkouts.


## Proof of actual simultaneous organization-wide jobs

Run from a trusted machine holding an existing authenticated \`gh\` session.
No token contents are ever written to the report:

\`\`\`bash
GITHUB_TOKEN="$(gh auth token)" \
  python3 scripts/github_actions_org_capacity.py \
    --org TrillionniumFoundation \
    --workers 8 --max-runs 1000 --max-run-pages 8 --include-queued \
    --output /tmp/hepta-gha-org-capacity.json
\`\`\`

The collector enumerates accessible active org repositories and workflow
runs, then paginates jobs and reconstructs execution time intervals. A job
is counted only when it has a real assigned runner, a trustworthy
\`started_at\`, and either \`completed_at\` or an in-progress observation
whose conservative end is the **start** of its job GET request.

The terminal-only interval peak is the proof used for the 500-runner verdict.
Each contributing job must have a positive integer runner ID and an actual
completion timestamp. A runner contributes at most one simultaneous slot.
In-progress observations remain an estimate because API state can be stale;
they cannot make `verified_500_running` true. The legacy
`peak_provable_concurrent_jobs_lower_bound` field remains for compatibility,
but the current proof is `peak_terminal_concurrent_jobs_lower_bound`.
Neither peak is computed by summing non-atomic "in_progress" counters.
Missing repos/pages/permissions or API errors are recorded as incomplete.
With `--include-queued`, the collector scans both `in_progress` and `queued`
parent workflow runs, because a queued parent can already contain assigned,
executing child jobs. Parent IDs are deduplicated across pages and statuses,
and in-progress parents take priority if the global run limit is reached.
Per-status provider counts, page limits, omitted parents and failed reads are
reported explicitly; provider run counts must not be summed as distinct runs.
The compatibility default scans only in-progress parents and records that
queued-parent children are outside that scope. Increase the explicit sampling
limits only when a report identifies truncation.
The collector cannot claim that **500 was actually reached** unless completed
intervals on at least 500 distinct runner IDs overlap. It does not register,
create, cancel, retry or
dispatch workflows. GitHub org-level metrics can provide corroborating
historical performance and queue-delay trends.

A separate direct API queue census on 2026-10-17 04:26 UTC enumerated
443 workflow runs marked queued: 161 newer than one hour and 282 older
than one day. A bounded 103-run sample found 58 zero-job records and
45 with jobs, with no API failures. It is incorrect to interpret all
443 queued workflows as runnable Jobs or platform capacity demand.
The sampled historical zero-job records were left untouched.

## Historical live Pocket4 org estimate

A separate authenticated read-only organization snapshot from
2026-10-17T04:33:10Z through 04:33:32Z covered 30 visible active
repositories, 18 in-progress workflow runs and 224 Job records.
Seventy-nine in-progress Job records were seen non-atomically; the original
collector estimated an 80-job overlap at 04:33:10Z. This live-state estimate
requires terminal reconciliation under the current proof rules. All read
paths returned complete without API errors.
This does **not** establish a maximum available concurrent capacity,
does **not** establish a 500-job peak, and does **not** include every
recently completed workflow.


## Short-run vs 250-job head-of-line admission comparison (scatter)

GitHub can report hundreds of *real* pending jobs even when only a small
number of already admitted jobs are running. This is independent of the
published Enterprise concurrent-job ceiling. A 250-job run may have a
different scheduling/admission profile than several 50-job runs. Test this
without duplicating work by setting \`absolute_offset=true\` and aligning
\`start_index\` with \`per_cohort\`.

Example: ten separate \`workflow_dispatch\` calls using
\`mode=fanout\`, \`execute=true\`, \`cohort=A\`, \`runner=ubuntu-24.04-arm\`,
\`per_cohort=50\`, one *identical* pinned \`source_sha\`, and
\`start_index\` values 0, 50, 100, ..., 450. This produces **500 distinct
actual test method identifiers in ten independent concurrency groups**;
none rely on a \`plan\` job to become runnable.

For a low-cost scheduler comparison first use two runs with
\`per_cohort=16\`, \`start_index=0\` and \`16\`. Wait for actual runner
allocation, not merely run creation. The legacy two-cohort A/B mode is
unchanged when \`absolute_offset=false\`. Malformed/unaligned coordinates,
unknown per-cohort sizes, insufficient real tests and a wrong source SHA
fail closed.

This design does **not** guarantee 500 *simultaneously running* jobs:
individually short tests and GitHub's runner admission rate can keep the
peak far below 500 even if all 500 jobs eventually complete. Measure
actual overlapping execution intervals with the org-capacity audit.

## Packed real-test throughput mode (opt-in)

The full 2×250 test-per-Job workflow proved **500 real completed successes** in
2026-10-17, but **only 8 actually overlapped** because 250 workers spent
70–90 minutes median in GitHub runner admission and each assigned Job took
a median of 6 seconds. Additional one-case-per-runner dispatches waste network
and scheduling overhead rather than creating useful compute concurrency.

\`.github/workflows/github-actions-fleet-packed.yml\` is an independent,
manual-only throughput experiment for exactly the *same* source-bound cohort
partition: choose A and B, the same complete Git commit SHA, \`workers=16\`,
and an appropriate Linux hosted runner label. This creates **16 real workers
per cohort, each executing 15–16 different Python unittest methods**
(32 workers for the 500 distinct tests). Alternatives 8/32 supported.
Each runner downloads/checks out source **once**, then invokes individual
\`unittest\` methods in fresh Python child processes.

\`scripts/github_actions_packed_ci.py\` enforces:
- Exact 40-hex checkout SHA and clean Git worktree before and after each case.
- Deterministic, gap-free A/B 250-method partition; no test-case duplicates.
- Independent worker scheduling by \`case_index % worker_count\`.
- Per-case execution in a new Python subprocess with a bounded 120-second
  timeout; failures/timeouts are retained, never reclassified as success.
- Atomic JSON receipt after every case, recording each exact method ID,
  exit status, observed milliseconds, and SHA256 of captured output.
  The workflow uploads this receipt even on a failed worker.
- Success only if every assigned case actually completes and passes.
  Missing receipt, skipped case, source mutation, or invalid arguments fail.

This is **not** a way to claim 500 concurrently running Runners. Its
purpose is to reduce the number of queue admissions and GitHub source fetches
needed to execute the same 500 real cases, then compare *elapsed wall-clock
time, queue latency, actual CPU-time throughput and failure evidence*.
The original 2×250 and org-wide overlap-proof code remain available and
unchanged. This packed workflow has no secrets or elevated permissions and
cannot write to the repository.

## Single-run ALL 500-case packed throughput mode

The separately validated 16 + 16 worker runs each completed 250 real cases,
but their runner admissions were staggered. To avoid a second cohort dispatch,
the packed workflow now accepts cohort=ALL as well as A/B. A single
16-worker GitHub matrix partitions exactly the disjoint canonical A+B union
of 500 real unittest identifiers (31-32 unique cases per worker); 8 and 32
worker controls remain available. Source SHA pinning, independent subprocess
execution, per-case atomic receipts, timeout and source-mutation rejection
are the same as the existing successful A/B packed baseline.

ALL is an opt-in throughput comparison, not a claim of 500 simultaneously
running hosted Runners. The original 2x250, 16+16 packed runs, and their
proven 500 unique passing case IDs and SHA256 manifests remain immutable.
Compare actual start/finish timestamps and download/checkout errors of the
single ALL run against the prior two dispatches on equivalent source tests.

## Security: checkout immutable GitHub event SHA, never a supplied SHA reference

GitHub CodeQL's PR check identified two high-severity potential
cache-poisoning flows: accepting a workflow_dispatch user-supplied
source_sha as the actions/checkout ref. Both Fleet workflows now
explicitly check out the GitHub-trusted event identity
(github.sha), **not** the untrusted source_sha input.

For manual dispatch, select the branch/tag ref that points to the
exact commit you wish to test and enter its complete 40-character SHA
as source_sha. Each worker compares that input against the Git checkout
HEAD and refuses execution if they differ. A moving branch or older
arbitrary commit cannot be silently substituted. Existing read-only
repository permissions and persist-credentials:false are preserved;
no cache-poisoning alerts are dismissed by policy exceptions.

## Strict packed unittest receipts (2026-10-17)

Packed execution now records the complete standard-library unittest result,
rather than treating an exit code of zero as proof that a test passed. Each
case runs in its own Python process and writes a separate temporary JSON
report after the test runner returns, including class/module teardown and
cleanup outcomes. The parent writes the retained worker receipt.

A case is `passed` only when the child exits with zero, the report identifies
the expected target, exactly one test ran, that target started and stopped
exactly once and received one success, and there are no failures, errors,
skips, expected failures or unexpected successes. Successful subtests remain
supported. A missing report after an early clean exit, an incomplete lifecycle
or a different target cannot count as a pass. stdout/stderr remain logs and
cannot replace the structured result.

The per-case `unittest_result` field retains the report. Non-passing case
statuses distinguish `skipped`, `expected_failure`, `unexpected_success`,
`test_error`, `missing_report`, `invalid_report` and `incomplete_test`.
Existing failure/timeout outcomes, exact-source checks, atomic receipts and
execution of subsequent cases are preserved. These reports describe normal
unittest execution; they are not a sandbox for hostile same-user Python code.

Validation: the planner, organization interval collector and packed runner
modules passed 41 tests together. Additional independent real subprocess
checks covered class-setup skip/error, subtest skip, import errors, missing
methods, paths containing spaces and successful-case-to-early-exit ordering.

## Full historical 500-job interval verification

A bounded read of three job pages for each completed run independently
verified the earlier admission comparison:

| Metric | Cohort A | Cohort B |
| --- | --- | --- |
| Run | [39004837428](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39004837428) | [39004840761](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39004840761) |
| Assigned execution jobs | 250 | 250 |
| GitHub job conclusions | 250 success | 250 success |
| Median admission wait | 4,216 seconds | 5,354 seconds |
| Median assigned job duration | 6 seconds | 6 seconds |

Both runs used source
`f462a687a3fdc675c548bd9c262a8dad9fc7dd6d` and
`ubuntu-24.04-arm`. Each API result had another three skipped non-execution
records. All 500 execution jobs had nonzero runner IDs and valid timestamps;
there were no duplicate job IDs or mixed attempts. Half-open execution
intervals `[started_at, completed_at)`, releasing ends before starts at the
same timestamp, give a combined peak of **8**, first reached at
**2026-10-17T06:28:05Z**.

This is the complete peak for those two runs, not the organization entitlement.
The historical success count is GitHub's job conclusion, not a fresh review of
every assertion or proof that the older harness rejected skips.

## Effective Maximum confirmed; execution remains separately measured

The earlier request to verify effective quota is closed: on 2026-10-17 the
operator read the organization's actual hosted-runner setting and confirmed
`Maximum = 500`. This evidence comes from the operator's settings observation,
not an inference from the organization's subscription name. Further execution
does not require repeating the quota check.

When already-materialized root jobs have no dependencies and still lack a
runner, increasing `max-parallel` adds demand without proving additional
provider capacity. Use actual assignment waits and runner execution intervals
to diagnose that condition. The packed ALL mode remains a throughput tool for
500 test methods; its 8/16/32 worker jobs do not establish 500 concurrent runners.

References:
- https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/view-current-jobs

## Strict direct fanout and confirmed Maximum (2026-10-17)

The operator has read the organization's actual hosted-runner `Maximum` as
**500**. This is an operator-confirmed settings value, closing the earlier
unknown-quota item; actual simultaneous execution must still be measured.

The direct 250-job A/B workflow now uses the same strict `run_cases` parent as
the previously validated packed execution. It validates the selected case and
source SHA against the source-bound plan, requires a complete successful
unittest lifecycle, and retains both the plan and the final result with
`if: always()`. Artifact names identify the run, attempt, cohort and shard.
A zero exit with a skip, expected failure or missing result remains a failure.

For 500 unique jobs, dispatch A and B once each with `per_cohort=250`, the same
exact `source_sha`, `absolute_offset=false`, and `start_index=0`. A selects
cases 0–249 and B selects cases 250–499. In absolute-offset mode the cohort
letter does not change the slice; equal start indexes would repeat cases.
The two cohorts have separate concurrency groups and neither depends on a
planning runner. Existing unrelated organization jobs also consume slots.

The workload remains 500 real, distinct tests. Short tests may complete before
later runners are allocated, so dispatching 500 jobs alone does not establish
a 500-job overlap peak. Measure real runner assignments and half-open job
execution intervals; report queue waits, completed strict results and the
observed peak separately. Do not pad test runtime with sleep or a start barrier
to manufacture concurrent occupancy.

## Queued-parent correction and independently verified organization evidence

A read-only snapshot on 2026-10-17 enumerated both `queued` and `in_progress`
parents across 30 active repositories, then completed the job-page reads from
11:16:34.675 UTC through 11:19:57.911 UTC. It covered 648 unique parent runs
and 2,997 unique job records, with no missing job pages or read errors in that
declared scope. Parent status counts are non-atomic and can overlap during
pagination; deduplicated IDs define the sampled set.

An independent live-interval sweep estimated **177 jobs on 177 different
runner IDs at 11:16:34.675 UTC**: Linux 90, Windows 37 and macOS 50.
Of the 177 assigned in-progress job records observed during the scan, 157 were
under parents returned by the queued-run query. A separately closed job
interval also contains the entire request/response window in which its parent
was returned as queued, confirming that this is not merely a cross-request
timestamp comparison.

Completed jobs use their actual completion time. In-progress jobs contribute
only until the start of their job-list request, and interval ends are processed
before starts at an equal timestamp. This historical live-state estimate
needs terminal reconciliation under the current proof rules. It is not the
configured maximum, a full historical peak, or
evidence that the separate 500-job test fleet reached 500-way overlap.

A later supplemental scan of the other nonterminal parent statuses found no
assigned running children; it is a separate observation, not an atomic part of
the earlier interval proof. Private repository names and job inventories are
retained in the operator's audit evidence, not in this public document.

## Admission review and packed slim qualification (2026-10-18)

The strict direct A/B runs
[39026346010](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39026346010)
and
[39026349331](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39026349331)
completed 500 distinct strict test cases at source
`1233fcff06a57901d80c3bbffefd6fec6b94496b`. Their combined completed-job
overlap peak was **7**. Case success and simultaneous runner capacity remain
separate results.

A fresh, fixed-attempt, complete-page review of six later pilots found all
114 execution jobs assigned and successful, including their strict test and
artifact-retention steps. These step conclusions do not constitute a fresh
download or digest check of those 114 artifact ZIPs.

| Run | Pool | Jobs | Completed interval peak | Median job queue wait | Run elapsed |
| --- | --- | ---: | ---: | ---: | ---: |
| [39092063202](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39092063202) | Ubuntu x64 | 16 | 2 | 3,836 s | 4,326 s |
| [39092067486](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39092067486) | Ubuntu ARM | 16 | 1 | 1,819.5 s | 2,457 s |
| [39092538398](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39092538398) | Ubuntu slim | 16 | 4 | 1,379 s | 1,995 s |
| [39092618348](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39092618348) | Ubuntu slim | 50 | 3 | 3,397.5 s | 4,101 s |
| [39099796658](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39099796658) | Ubuntu slim | 8 | 1 | 246 s | 599 s |
| [39099823808](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39099823808) | Ubuntu x64 | 8 | 2 | 2,252 s | 3,689 s |

Queue wait is `job.started_at - job.created_at`; elapsed is
`run.updated_at - run.created_at`. Each run is attempt 1. Peaks use half-open
completed intervals with ends released before starts at the same timestamp.
The six runs used different pinned revisions and admission windows, so the
table does not isolate runner label as the sole cause of the differences.
The long queue waits and 10–12 second median job durations motivate reducing
the number of runner allocations per complete 500-case execution.

The packed workflow now accepts opt-in `runner=ubuntu-slim`, keeping the
existing ARM default. It allows 15 minutes on slim and 90 minutes on the VM
pools. Its concurrency key includes the runner label so separate pool
comparisons do not serialize each other. The packed selftest and the blocking
workflow's Python/Bash scope and verdict jobs use slim; their checks, dependency
relationships and failure conditions remain intact.

To qualify packed slim throughput, dispatch one source-pinned `cohort=ALL`,
`workers=8`, `runner=ubuntu-slim` run. Require all eight receipts to cover the
same exact 500-case source set once, with no skipped or missing results.
Measure its actual elapsed time and completed interval peak. A packed success
still does not establish 500 simultaneous runners; do not pad execution with
sleeps or barriers to raise occupancy.

The organization collector now deduplicates job IDs before sweeping intervals,
retains the largest observed pagination total, and permanently excludes
conflicting IDs across parent runs. Duplicate API pages cannot satisfy read
completeness or inflate the peak. Terminal proof requires positive integer
runner IDs; name-only observations cannot manufacture capacity. Reconcile
live witnesses after completion before accepting a new 500-runner verdict.
