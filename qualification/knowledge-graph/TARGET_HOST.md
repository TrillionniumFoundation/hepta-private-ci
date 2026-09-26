# knowledge.graph production target-host qualification

This document defines the first production-admission host profile and the evidence boundary for `knowledge.graph`. It does not activate or release the module. The executable policy is [`PRODUCTION_QUALIFICATION.json`](PRODUCTION_QUALIFICATION.json); the repository acceptance state is [`ACCEPTANCE_STATE.json`](ACCEPTANCE_STATE.json).

## Named target profile

The first named profile is `rog-linux-x64-kg-v1`.

| Property | Required value |
|---|---|
| GitHub runner name | `rog` |
| Runner labels | `self-hosted`, `linux`, `x64`, `rog` |
| Runner OS / architecture | `Linux` / `X64` |
| Source ref | exact commit reachable from `refs/heads/main` |
| Execution isolation | non-blocking host-global `flock`; concurrent admission is rejected |
| Build | release, locked dependencies, zero retries |
| Workload | 256 mutations, 100 queries, 20 reopens, 8 readers × 20 contention rounds |
| Canonical scale | 4,096 logical nodes and 32,768 logical edges |

A shared GitHub-hosted runner is useful for regression and diagnostic evidence but is never a production target-host receipt. A manually supplied profile name is also insufficient: the runner envelope must match the exact name, labels, ref, commit and source tree.

The target workflow has no pull-request trigger. It runs from trusted `main` by `push` or controlled `workflow_dispatch`, checks that the selected candidate is an ancestor of `main`, uses a read-only token and checks out the exact SHA. Untrusted pull-request code therefore cannot directly schedule execution on the self-hosted host.

## Admission budgets

The following are initial fail-closed admission ceilings, not universal customer-facing SLOs.

| Measurement | p95 ceiling | p99 ceiling |
|---|---:|---:|
| Mutation | 2.0 s | 4.0 s |
| Query | 100 ms | 250 ms |
| Reopen | 2.0 s | 4.0 s |
| Contended writer | 2.5 s | 5.0 s |
| Contended reader | 250 ms | 500 ms |

Peak RSS must not exceed 6 GiB. Final database plus WAL must not exceed 1 GiB and its fresh-database growth divided by the 256 measured mutations must not exceed 4 MiB per mutation. A target-host miss blocks admission; it is not converted into a warning. Changing a ceiling requires a separately reviewed policy commit and a fresh exact-SHA run.

The receipt must report the selected incremental writer, a full-rebuild oracle interval of 64 generations, and the remaining scale boundary: complete physical source-cut assembly plus reopen digest scan. Passing the host budget does not erase that boundary.

## Required evidence

The Actions workflow retains the online artifact for 90 days, the maximum portable repository-local window used by this project. Before that artifact expires, the named operator must export the exact SHA-256 manifest and every listed object into the append-only archive retained for at least 365 days:

- exact source commit and tree;
- host and runner metadata;
- structured target-host JSON;
- raw benchmark and driver logs;
- kernel log;
- crash/reopen rollback-rehearsal log;
- production-gate admission JSON and log;
- SHA-256 manifest over every retained object.

The gate verifies the raw-log digest, profile, workload, canonical cardinality, runtime writer, oracle interval, p95/p99, RSS, DB/WAL growth and exact source identity. Missing, malformed, duplicated or over-budget evidence fails closed. A successful Actions upload is not by itself proof that the required long-term archive was completed.

## Checkpoint, retention and archive

The operational policy is:

1. An online `PASSIVE` WAL checkpoint is due every 64 generations or when WAL reaches 64 MiB, whichever occurs first.
2. `TRUNCATE` checkpoint is maintenance-only and requires the same exclusive owner fence as mutation.
3. Hot generation receipts are retained for at least 90 days.
4. Every 1,024 generations or 24 hours, whichever occurs first, immutable content-addressed archives are produced for generation receipts, publication receipts, source frontier and admission receipts.
5. Actions qualification artifacts are retained online for 90 days and exported into immutable storage retained at least 365 days; evidence supporting an activated release is retained at least 2,555 days.
6. Every archive is append-only and SHA-256 bound. Archive failure does not authorize receipt deletion or pointer advancement.

This policy defines the production obligation. The target-host workflow proves measurement and rollback behavior; a named production operator must separately prove checkpoint and archive execution before acceptance.

## Acceptance, canary and release boundary

A successful target-host admission remains insufficient for activation. `ACCEPTANCE_STATE.json` stays inactive until all of the following are exact-candidate-bound:

1. target-host admission;
2. independent semantic review by an actor distinct from the source author;
3. operator acceptance;
4. rollback rehearsal;
5. canary acceptance.

Each accepted gate requires a SHA-256-bound receipt and actor identity. Release additionally requires activation. The repository gate rejects `release=true` while activation is false and rejects activation when any required gate is absent, pending, rejected, bound to another candidate or self-reviewed.

The current repository state intentionally keeps `activation=false` and `release=false`.
