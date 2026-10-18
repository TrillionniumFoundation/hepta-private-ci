# RUNNING_TASKS

Captured 2026-10-18T15:30:22.998491+00:00 (UTC), host `2313cba36518`.

## Scope

Accessible executor only; not independently identified as the user's Dot or dedicated Hepta host.
Protected cwd/fd entries return null; absence here does not prove remote absence.
Remote Dot/SSH hosts and organization runner management are NOT_ACCESSIBLE. No absence claim is made for them.

## Resources

Visible CPUs: 9; cgroup CPU quota: `800000 100000`.
Cgroup memory limit: 8589934592 bytes. Free disk: 0.0 MiB.
Rust 1.95.0 and just 1.51.0 were separately verified from existing read-only runtime paths; they are absent from the default PATH.

## Processes observed now

These rows are observations, not promises of continuing background execution.

| PID / PPID | Start UTC | State | CPU % sample | RSS MiB | Program | cwd |
|---|---|---|---:|---:|---|---|
| 1 / 0 | 2026-10-18T01:02:38.320000+00:00 | S | 0.0 | 22.3 | supervisord | / |
| 3 / 1 | 2026-10-18T01:02:39.490000+00:00 | S | 0.0 | 2.1 | rsync | / |
| 4 / 1 | 2026-10-18T01:02:39.500000+00:00 | S | 0.0 | 1.9 | sync_share.sh | / |
| 5 / 1 | 2026-10-18T01:02:39.500000+00:00 | S | 0.0 | 1.9 | sync_share.sh | / |
| 6 / 1 | 2026-10-18T01:02:39.500000+00:00 | S | 0.0 | 0.3 | caas-prefix-tra | / |
| 7 / 1 | 2026-10-18T01:02:39.500000+00:00 | S | 0.0 | 0.1 | sites-preview | / |
| 81 / 4 | 2026-10-18T01:34:57.880000+00:00 | S | 0.0 | 0.8 | inotifywait | / |
| 132 / 1 | 2026-10-18T01:35:02.750000+00:00 | S | 0.0 | 67.4 | codex | / |
| 302 / 1 | 2026-10-18T02:50:55.730000+00:00 | S | 1.0 | 108.9 | codex | / |
| 400739 / 302 | 2026-10-18T15:30:20.620000+00:00 | R | 0.0 | 11.0 | python | /workspace/scratch/855e2f95cede |
| 400760 / 5 | 2026-10-18T15:30:21.460000+00:00 | R | None | 9.2 | inotifywait | / |

Redacted argv, output destinations, process counters and collection commands are in `host_snapshot.json`.

## Existing worktrees

All existing trees were inspected read-only. Unix UID and directory names do not establish an independent Agent owner.

| Worktree | Branch | HEAD | Dirty paths |
|---|---|---|---|
| `/dev/shm/hepta-github-inventory-855e2f95cede/repo` | `audit/pr2599-source-rebind` | `19c5cd41c17dd42da7afac96203a4bc7901e23a6` | 0 |
| `/workspace/scratch/28fd839d6e0d/hepta-intent-2816` | `DETACHED` | `4afd485aaed4a539e7f812a7952e92d9284f8447` | 0 |
| `/workspace/scratch/28fd839d6e0d/hepta-private-ci` | `DETACHED` | `f8c9419df6ddeb36ff8b522a50219981fb8d9345` | 0 |
| `/workspace/scratch/28fd839d6e0d/p0-cell-review/worktree-2818` | `DETACHED` | `5b25b9e8e10101b519079425d55f8e5b65ed98ee` | 0 |
| `/workspace/scratch/855e2f95cede/audit/github_inventory/pr1350-refresh` | `audit/pr2599-typed-fixtures` | `1ebb9b8a9313e6504d2ebf9597412f3fe9c49d9e` | 4 |
| `/workspace/scratch/96b7abe29372/hepta-audit-20261018` | `audit/full-inventory-20261018` | `f8c9419df6ddeb36ff8b522a50219981fb8d9345` | 1 |
| `/workspace/scratch/96b7abe29372/hepta-handoff/desktop/repo` | `fix/a06-cpu-max-strict-parser-20261018` | `f99826707ed531a08d52920ec41ee4c4c26c2ece` | 0 |
| `/workspace/scratch/96b7abe29372/hepta-keyring-2790` | `fix/keyring-encrypted-sync-closure-20261018` | `1bf238eb062ffe31c7d109605fcb8b1ddd2aacbe` | 1 |
| `/workspace/scratch/96b7abe29372/hepta-memory-1452` | `DETACHED` | `52b89310ecd455273518fe4dd3d423c8f5650c9d` | 0 |
| `/workspace/scratch/96b7abe29372/hepta-memory-fresh-2a0e8d` | `DETACHED` | `2a0e8d016f5e00359561934909e801ae26f2bfd7` | 0 |
| `/workspace/scratch/96b7abe29372/hepta-memory-shard-gates-1452` | `fix/memory-shard-original-budget-20261018` | `2a0e8d016f5e00359561934909e801ae26f2bfd7` | 0 |
| `/workspace/scratch/96b7abe29372/hepta-private-ci` | `main` | `f8c9419df6ddeb36ff8b522a50219981fb8d9345` | 0 |
| `/workspace/scratch/96b7abe29372/hepta-sqlite-2805` | `fix/migration-sqlite-lifetime-2805-20261018` | `477bb86f230c882de5c83ad0e393214d13b2be98` | 0 |
| `/workspace/scratch/96b7abe29372/hepta-windows-2813` | `DETACHED` | `13877a5fdefae2c7758ba511284c8b2004aebc44` | 0 |
| `/workspace/scratch/d7da9e7650f0/a01-current` | `agents/A01-asterinas-boot` | `71524be19383e2ff98f6abc90668c48988e7c8e2` | 0 |
| `/workspace/scratch/d7da9e7650f0/a01-mainf9` | `DETACHED` | `f9e306f76154590e096a42f70ce9de0a7c859e60` | 4851 |

## Status and next action

| Item | Status | Next action |
|---|---|---|
| Current audit/fix owners | RUNNING | Root owns environment/publication; inventory owns #2599 comparison; CI agent owns failure evidence; research agent owns #2714 receipt validation. Each writes a separate directory. |
| Other worktree owners | UNKNOWN | Preserve their dirty files and metadata; use independent clones and remote compare-and-swap before publication. |
| Dedicated host / organization runners | BLOCKED_EXTERNAL | Supply an accessible configured project endpoint or runner-admin capability; no credential or protection workaround. |
| Disk for full native builds | BLOCKED_EXTERNAL | Current free disk is insufficient for a fresh full Hepta workspace build. Preserve other owners' caches; scoped Python/static validation can proceed. |
| Fresh 112-call attempt-03 by another owner | FAILED | Six calibration answers and zero evaluation answers completed before the watchdog failure. The separate historical 40+72 archive is not a fresh run. This audit made zero new model calls. |
| Exact HEAD required CI | QUEUED / FAILED | See CI_MATRIX.md and BLOCKERS.md; remote required checks remain mandatory. |

## Reproduce

`python /workspace/scratch/855e2f95cede/audit/environment/capture_environment.py`
