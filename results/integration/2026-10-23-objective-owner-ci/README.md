# Original Objective owner package CI candidate

## Status and scope

This is a **source and syntax validated candidate**, prepared for Hepta PR #3444 on `agents/20261023/original-objective-sender`. The publisher supplied base head `cc5cb3ab71c48d387fcdd660ef0e42e9319d9b18`, tree `c01ee459f0f3ab9b226f041e2e2739d8a59f32b9`. Its executable owner source remains the separately qualified `db91f9ec316ba1472e7adf97f8415949de012469` version. Publication must recheck the current branch and the new workflow path before its compare-and-swap update.

Only `.github/workflows/hepta-objective-owner.yml` is added. The old HOS2 proposal workflow and its branch guard are unchanged. No Cargo manifest, lock, Rust source, test oracle, production capability, or environment-dependent refusal is edited. This local task executes no Cargo command, GitHub operation, embedded workflow program, or CI job.

## Existing coverage and why this gate is separate

The original workflows and setup scripts were read from locally retained Git blobs at head `16418ddc3416a38a122b883cee46e2d3583cbd41`, tree `43fde98e9ea789b81b941e48bb65300c76c4292c`. Their file hashes are preserved in the input manifest. This is a source review, not a claim that any remote workflow has executed on the new PR.

- `.github/workflows/hepta-production-hos2-proposal.yml:31–34` restricts `owner-candidate` to the same repository and branch `codex/production-hos2-delivery-20261020`. It also generates candidate postimages and explicitly does not qualify the input HEAD. The new owner branch does not satisfy that guard.
- `blocking-ci.yml:123–175` has an existing exact-head affected-owner route. It calls the original dependency selector, whose test command is `just test --locked` on affected owners and reverse consumers. It can include complete memory and Agentd packages, but it runs only when `native=true` and `full_repo!=true`; it is not an unconditional replacement for this requested two-package plan or its source/lock/JUnit assertions. Its outcome on the new remote head was not queried in this task.
- The fast `rust-ci.yml` route has manifest, format and other fast checks; the general full test matrix is in `rust-ci-full.yml`, which is callable/manual, triggered by `**full-ci**` branch pushes, or invoked from main postmerge. This does not establish completed source-head owner tests for the stacked PR.
- `hepta-consolidated-source.yml` can run complete impacted owners and strict scoped Clippy; it is declared `workflow_call`/`workflow_dispatch`, and no caller was found in the inspected original workflow files. `hepta-gap-agentd-process.yml`, `hepta-lane-b-truth.yml` and `hepta-knowledge-graph-qualification.yml` are also callable/manual routes with different package or test coverage. The original automation-focused Agentd library job is limited to a different push branch/manual entry.

The new workflow has a normal `pull_request` trigger for the Rust tree and its CI inputs, including draft PR opening/synchronization, with no head-branch allowlist, draft exclusion or dependency-selector early success. It qualifies the exact source head only; it does not replace prospective merge, architecture, Bazel or other original gates.

## Concrete execution plan after publication

One `ubuntu-24.04` job runs serially, with a 240-minute outer limit, `CARGO_BUILD_JOBS=1`, `CARGO_INCREMENTAL=0`, the original `dev-small` profile and one test thread. It records available memory/disk before and after commands. These are explicit concurrency/time bounds, not a promise that a hosted runner has enough resources; setup, compile or timeout failure must remain failure/not-started evidence.

Checkout uses the immutable `pull_request.head.sha`, full history and no retained credentials. The exact PR base commit is required for the original formatting scope. Before setup, the runner records every actual tracked file's Git blob, SHA-256, executable/symlink mode, source head/tree and locks. Every command repeats actual file reads and compares them with the frozen inventory; it does not trust an empty Git diff alone or ignore `assume-unchanged` files.

The existing `prepare-bazel-ci` action supplies the original setup, just, DotSlash and cache environment. Its local action code is part of the source-head inventory. External action SHAs are reused verbatim from existing repository workflows. The pinned compiler is Rust 1.95.0 with the original clippy/rustfmt/rust-src components; nextest is the existing CI version 0.9.103. The native setup explicitly installs `libssl-dev` and the original native prerequisites, uses `/usr/include` and `/usr/lib/x86_64-linux-gnu`, and verifies the OpenSSL pkg-config directory.

V8 setup calls the original `scripts/hepta_ci_v8.py` and packaging resolver. Preexisting archive/source-build overrides are cleared for that step so the original checksum-verifying path supplies both the archive and binding. Their resulting identities are recorded using streaming SHA-256; no alternative download or fake runtime is supplied.

The original `cargo metadata --locked --no-deps --format-version 1` must identify the unchanged complete 193-member workspace and both real owning packages. No reduced workspace, hand-edited lock, target manifest, or custom nextest metadata is created. The original just recipe retains its existing metadata wrapper and nextest configuration.

The unit gates are:

```text
just fmt --check --base <exact-PR-base-SHA>
just test --locked --cargo-profile dev-small --build-jobs 1 --test-threads 1 -p codex-hepta-memory --lib --no-tests fail
just test --locked --cargo-profile dev-small --build-jobs 1 --test-threads 1 -p codex-hepta-agentd --lib --no-tests fail
just fix -p codex-hepta-memory --locked --profile dev-small --lib
just fix -p codex-hepta-agentd --locked --profile dev-small --lib
just fmt --check --base <exact-PR-base-SHA>
```

There is no test-name/filterset restriction. Independent package and lint steps can still produce evidence after an earlier test failure; every step first rejects any source drift, and the final job remains failed unless all original gates pass. `just fix` is the real original recipe; any write it makes to source or locks causes failure rather than being treated as a newly qualified postimage. Its exit zero is not a zero-warning or `-D warnings` claim.

Each package must produce a fresh original JUnit report. The job archives the previous package's report before clearing the generated report for the next package, preventing stale-JUnit reuse. It checks the workspace-relative nextest store and the configured Cargo target store, and rejects ambiguous or missing reports. JUnit and the untouched nextest stdout/stderr retain the actual executed, failed and skipped/retried information. The repository's default nextest **one retry** is preserved; a final success is not asserted to mean zero retries.

The memory report must contain both checked-observation regressions and all three acknowledged-snapshot regressions. The complete Agentd report must contain the three new bridge tests and the original factory (at least 7), Notes (5), protected authority (5) and final-use issuer (7) groups. These checks inspect executed passing testcases, not selector output or static source definitions. Independent read-only review compared these module aliases/function names with the actual db91 source and the original nextest profile/store paths.

## Evidence and qualification boundaries

The artifact upload uses `always()` and a source-SHA/run/attempt-bound name. An attempt receipt exists before checkout. Commands retain complete separate stdout/stderr, exit code, source/lock checks, resource snapshots and timestamps. Test indexes and raw JUnit are archived separately for each package. Setup outcomes, unexecuted command states, final source verification, a drift patch and an artifact hash inventory are retained on failure as well as success. Success requires all mandatory setup/command outcomes and final source equality.

The terminal receipt always keeps `full_workspace_qualified`, `bazel_qualified`, `native_guest_qualified` and `production_checkpoint_implemented` false. Passing these two original package libraries cannot supply the missing production current-cut checkpoint, authorize an old-schema upgrade, qualify actual model/device operation, or establish deployment readiness. The 193-member claim concerns the original complete input workspace; the execution scope is two owning packages, not 193 package suites.

## Actual local validation

`validation/candidate-syntax.json` and `validation/local-execution.json` record the real local checks: YAML parsed with duplicate-key rejection and explicit shape assertions; all 12 Bash blocks passed `bash -n`; all 4 embedded Python programs passed AST parsing and compilation without execution; external actions matched known original full SHA references. The validator and raw local stdout/stderr are retained. No GitHub actionlint binary was available or run, and no GitHub execution result is claimed. The first published run remains the required check of actual runner setup, dependency compatibility, compilation and both complete package suites.
