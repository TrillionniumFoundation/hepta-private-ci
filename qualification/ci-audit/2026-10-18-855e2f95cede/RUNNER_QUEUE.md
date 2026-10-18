# Active workflow and queue snapshot

Observed 2026-10-18T14:31:49.037Z through 2026-10-18T14:32:35.155Z (UTC).

All latest-attempt job pages were read for the 441 runs in the nonterminal status-filter sweep. This is a changing observation interval, not an atomic GitHub snapshot or a full historical Actions inventory. All 1,587 job records matched their requested run ID and source HEAD.

| Job status | Count |
|---|---:|
| queued|null | 494 |
| completed|cancelled | 220 |
| completed|success | 393 |
| completed|failure | 137 |
| in_progress|null | 168 |
| completed|skipped | 175 |

Queued job age at its observation: median 24.56 minutes, p95 61.62 minutes, maximum 76.99 minutes.

168 jobs were observed in_progress in this sampled run set. Organization-wide online/busy runner counts, groups and concurrency ceilings remain NOT_ACCESSIBLE; these job counts cannot establish organization utilization or spare capacity.

| Queued runner labels | Jobs |
|---|---:|
| ubuntu-24.04 | 235 |
| windows-latest | 95 |
| ubuntu-latest | 78 |
| macos-15 | 46 |
| ubuntu-slim | 28 |
| ubuntu-24.04-arm | 10 |
| self-hosted,linux,x64,rog | 1 |
| macos-15-intel | 1 |

The API sometimes populates started_at even while status remains queued and runner_id is zero. Such rows remain queued; started_at is not counted as execution evidence.

## Scheduling decision

No workflow was cancelled, no coverage or security gate was removed, and no unsupported organization runner API was bypassed. Required blocking-ci and architecture failures must be fixed on their existing owners. Pending metadata, fan-in jobs, and skipped build variants do not qualify a candidate. Before altering concurrency, inspect the exact workflow source and active owner dependencies; the current evidence does not isolate an organization-wide resource ceiling.

Normalized records are in active_jobs_snapshot.json.gz, with integrity and source-size receipt active_jobs_archive.json. Snapshot metrics can be recomputed from those exact records.


## Exact workflow source and zero-job runs

The exact main blobs of 51 workflow concurrency definitions were verified. Among the 441 observed nonterminal runs, 296 had no jobs in the fully paginated latest-attempt response: 255 had no branch in the branch snapshot, 32 had a different branch source SHA, and 9 matched. Those records do not establish occupied or available runners. The 96 repeated workflow/branch groups are review candidates; no automated cancellation was performed. See SCHEDULER_SOURCE_AUDIT.json.

No scheduling policy was changed. Administration access is needed to establish runner groups, online/busy totals, actual organization ceilings and the safety of a capacity change. No utilization improvement or queue reduction is claimed.
