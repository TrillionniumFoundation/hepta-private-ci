# kernel.evidence retained A–D diagnostics — 2026-09-29

## Scope

This record documents the fail-closed diagnostic retention repair added after
A–D run `36529136762` on candidate
`6dabd953afd6efbee653cdd19103abfb4e9823f3`.

The run retained early artifacts for both source-head and deterministic
fixed-main merge lanes. Those artifacts established only that candidate
binding, the isolated distinct-identity solver, the kernel.evidence Python
regressions and formatting isolation completed successfully. The package-level
step failed, but the old workflow marked its final inventory and final artifact
steps skipped, so the failing command logs and exact exit records were not
retained.

## Repair

Commit `a0c4585734badfa4c854857b9be84882985ef4c0` adds
`.github/workflows/kernel-evidence-ad-retained-diagnostics.yml`.

For both source-head and deterministic fixed-main merge lanes it:

1. binds the exact source, fixed base and tested commit/tree;
2. runs format, evidence, Agentd product, doctest, strict Clippy, build,
   Lane-A, canonical status, documentation and implementation-map checks under
   explicit deadlines;
3. records every command, timeout, start, finish, exit status and complete log;
4. records the final source identity and worktree state;
5. writes a SHA-256 inventory and uploads the artifact before evaluating the
   aggregate result; and
6. fails closed in a separate final step when any recorded check failed,
   timed out, did not run or left the tested worktree dirty.

The diagnostic workflow does not repair tested source, substitute a successful
result, inherit prior-head evidence or advance any qualification or external
authority gate.

## Claim boundary

The A–D implementation remains a candidate until the unchanged final object has
successful retained source-head and fixed-main-merge artifacts and the required
repository fan-ins succeed. Pending, queued, skipped, cancelled, action-required
or failed states are non-success.

Independent acceptance, deployment of the external rollback domain, witnessed
backup/restore and power-loss drills, measured capacity/RPO/RTO, canary,
promotion and release remain outside repository-authored authority.
