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
fleet tests. After adding sixteen planner/audit and org-peak regressions, 919 statically
recognizable unittest.TestCase methods were available in the local
source-only scan. Not all 909 were independently run. The planner selects
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

## Preview, pilot and full dispatch

1. Merge/activate the workflow on the default branch. Choose one complete
   40-hex Git commit SHA S containing the actual code to be tested.
2. Run mode=fanout, cohort=A, per_cohort=250, source_sha=S,
   execute=false. Repeat for cohort=B. Both jobs merely compute artifact
   plans, with 250 distinct tests each. The full manifest SHA256 must match
   between cohorts. The source SHA must match too.
3. Run a cheap, pinned per_cohort=2..8 pilot on each cohort and check every
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
    --workers 8 --max-runs 200 \
    --output /tmp/hepta-gha-org-capacity.json
\`\`\`

The collector enumerates accessible active org repositories and workflow
runs, then paginates jobs and reconstructs execution time intervals. A job
is counted only when it has a real assigned runner, a trustworthy
\`started_at\`, and either \`completed_at\` or an in-progress observation
whose conservative end is the **start** of its job GET request.

The maximum overlap of those intervals is a **provable lower bound** for
simultaneous running jobs, even when REST queries occur at different
times. It is never computed by summing non-atomic "in_progress" counters.
Missing repos/pages/permissions or API errors are recorded as incomplete.
The collector cannot claim that **500 was actually reached** unless at least
500 such intervals overlap. It does not register, create, cancel, retry or
dispatch workflows. GitHub org-level metrics can provide corroborating
historical performance and queue-delay trends.

A separate direct API queue census on 2026-10-17 04:26 UTC enumerated
443 workflow runs marked queued: 161 newer than one hour and 282 older
than one day. A bounded 103-run sample found 58 zero-job records and
45 with jobs, with no API failures. It is incorrect to interpret all
443 queued workflows as runnable Jobs or platform capacity demand.
The sampled historical zero-job records were left untouched.
