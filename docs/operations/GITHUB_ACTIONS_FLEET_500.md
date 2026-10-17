# GitHub Actions fleet: 500-job real test fanout

## What is implemented

- A default-off manually dispatched workflow:
  .github/workflows/github-actions-fleet-500.yml
- Source-only deterministic planner: scripts/github_actions_fleet_500.py
- Read-only GitHub API telemetry: scripts/github_actions_runner_audit.py
- Adversarial unit tests: scripts/test_github_actions_fleet_500.py

This machinery neither creates runner registrations nor purchases Larger
Runners. It does not cancel existing CI or bypass required checks.

## Verified baseline and limits (2026-10-16)

The public hepta-private-ci main commit
f8c9419df6ddeb36ff8b522a50219981fb8d9345 contained 76 Python test
files under scripts/, with 903 AST-defined test_* methods before adding
fleet tests. After adding six planner/audit regressions, 909 statically
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
**The organization plan and allocated quota have not been verified.**

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

