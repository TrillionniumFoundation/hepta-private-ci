# Fence v0.10: original inventory failure

The original job `130526677869` in run `43021840778` stopped before Fence readiness with `local_control_inventory_unavailable`. This bounded review found **no demonstrated configuration-only correction that preserves the pinned policy**. It made no host call, rerun, policy change, or source ref update.

## What the original record proves

The job ran the pinned `openai/fence@e6b39c80c51cb2b2a39448ddeff74b3b886c0a63` (reported v0.10.0) in audit mode with zero added allowlist entries. Its hosted image was Ubuntu 24.04.5 / `ubuntu-24.04` image `20261101.360.1`. The action began the resident at 12:37:04.1489099Z; the resident exited with status 1 before readiness at 12:37:05.6719530Z. The code was extracted from the service journal.

The exact workflow at head `9bd2f589debdba4a93baa363817c3669cb103721` and the actual executed merge `8644d1044c50c7d4bfa47834f2602d133433300d` has the same blob `d870b6f9c1e025aff458c32f0461c752fcd2f0b3`. It already runs Fence first, uses ubuntu-24.04, has no container job and uses audit. It passes the action's Linux/x64 check before launching the resident. The later missing local check-clean-worktree action and missing post-job mount evidence follow the failed setup and skipped checkout; they do not identify an independent inventory cause.

## Exact failure boundary

In `src/local_control.rs:447–483`, the verifier checks instability and bounds first, then rejects an Unavailable status/scan or any nonempty `unavailable_inputs`. The collection code can report process/table/FD/cgroup acquisition failures, root-or-ambiguous identity drift, malformed rows, unresolved Unix reachability and incomplete or unreviewed ownership. `public_snapshot` additionally derives reachability/ownership failure entries. The error code alone does not tell which reason occurred; it is not a diagnosis of one particular permission, network destination or new daemon.

`src/dns_mediator.rs:3084–3092` performs supported-host and local-control preflight **before** the audit/block branch. Audit then validates its local-control baseline before readiness (`2058–2076,2146–2184`). The original log does not identify which observation failed. Consequently audit mode is not a repair—the original execution already used it—and network allowlist/artifact inputs cannot supply this missing local evidence. The pinned input schema exposes no inventory bypass and accepts only the reviewed hosted profile.

## Evidence still needed

The missing item is the **original failed local-control observation**, including its status, stability, attempts, unavailable-reason enum values, bounds, malformed-row count and reachability/ownership completeness, tied to the original invocation and pre-activation/baseline phase. If already retained, a bounded resident report/journal may locate that failure. No protected file contents, credentials or process environment are needed for this initial distinction.

The action prints the extracted error code normally and places the last 20 journal lines in debug groups controlled by `RUNNER_DEBUG` / `ACTIONS_STEP_DEBUG`. However, its Rust CLI maps the error to a generic lifecycle message and the failing preflight drops the observation; debug output is therefore **not guaranteed** to contain the missing reason. Enabling debug and rerunning would be a new execution, not recovery of this original observation. This review did neither.

Without original retained diagnostic evidence, the precise subreason remains **UNKNOWN**. A later bounded diagnostic qualification would need a separate identity and unchanged checks. Altering accepted identities, turning off Fence, broadening rules or changing host ACLs on speculation would not be a demonstrated repair.

## Reproducibility

`READ_ONLY_REVIEW.json` contains the exact finding-to-source mapping and minimum missing fields. `SOURCE_INDEX.json` binds 18 complete pinned source files, including the workflow; source bytes were fetched and Git-blob verified, while the static review is limited to the named call paths. The original 3,859-byte job log remains unchanged (SHA-256 `f50cdc9fa4044764eaa7a79468bec7e0dae90b2aa103ec231bfced4d19267f00`). The file manifest and compressed packet preserve the review against local workspace resets.
