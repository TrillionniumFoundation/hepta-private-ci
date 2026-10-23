# compact.engine remediation — 2026-09-28

This record belongs only to PR #993, branch
`fix/compact-engine-current-main-convergence-20260925`.

## Starting source identity

- Starting head: `a11adf24c5bfe9d99f3695fe2ba91ebe12e48750`.
- Starting tree: `8a5481d768b9f416bb48ca3898a8cc2eec914105`.
- Pinned main for this review: `a126987b84737dbc2ee2592442a314117bddb4a2`.
- The starting head has the same source tree as `e569af77202ce91f2dd20c99f4e6ff8223990e15`: the temporary write-enabled workflow was added and then removed, but the Rust include-surface repair was not delivered by those two commits.

## Work and acceptance boundary

The work stays in the existing transaction-owner, trust-verification and Agentd product-adapter architecture. Source changes must be committed directly, never generated and pushed by a qualification workflow.

1. Repair the native source and require locked exact-head and pinned-base synthetic-merge checks, tests, strict Clippy and formatting.
2. Register every immediate write transaction with SQLx for cancellation-safe rollback. Check exact owner/root/lease/manifest at each durable mutation boundary; distinguish current execution time from historical event/acceptance time.
3. Enforce pairwise selector/generator/evaluator principal and key independence. Reconstruct historical evidence separately from current admission and integrate the authoritative product source.
4. Exercise crash/response-loss, migration rollback, concurrent writers, complete publish/reopen capacity and long-run retention/GC behavior.

## Evidence rules

A saved patch is not source delivery. A test file is not a pass receipt. SQLite subprocess/storage-contract tests are useful but do not stand in for native Rust, Agentd lifecycle or target-device power-loss qualification. Queued, skipped, cancelled and failed checks are not acceptance.

The existing read-only developer-toolchain archive is a development aid, not qualification. It contains tool binaries/sysroot, not source-generation scripts or credentials.

`productionImplementation`, independent acceptance, activation and release remain false until their separate gates are actually met. This record will be updated with delivered source and observed results rather than anticipatory completion claims.

## 2026-09-30 P0 qualification-identity closure

The convergence line now closes the repository-controlled identity gaps without adding a second owner or compaction architecture:

- SQLx 0.9 transaction executors in `recovery.rs` use the correct owned-transaction dereference, removing the common compile failure in exact-head, synthetic-merge and capacity lanes.
- `durable_fence_tests.rs` is an actual child of `durable.rs`; qualification rejects any mapped or crate-local Rust test source that is not reachable from the crate test graph.
- the authoritative coordinator layout is recorded as the nested `final -> guarded -> original` module chain; stale `durable_facade.rs` references are removed in favor of the real `durable.rs` plus `mutation_guard.rs` boundary.
- one focused workflow attempt now owns source snapshot, exact-head, deterministic synthetic-merge and full capacity evidence. A machine-generated readiness manifest binds every required identity/hash and fails closed; no result from another workflow run or attempt can be spliced in.
- `productionQualified` remains false until final-merge and post-merge evidence exists. This source change does not grant merge, activation, promotion or release authority.
