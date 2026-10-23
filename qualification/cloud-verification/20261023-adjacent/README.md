# Adjacent recovery boundary verification

Tested source: `74ba1d6c11659c2a3e38b4ef6056778f1d00a2a2`, parent `3d38cc6e786179661d213e815c9b4f0761b2664a`, tree `f6a505172eb6e6a50e28fc81ea7f76f1fce41b24`. Draft PR #3586; dependency #3582 stays at `2f7ae91c4176896d0b9caf9aea75ed3e030a81f8`. This increment changes only two existing test files; no production or authorization changes. No additional reproducible production defect was found.

## Completed

- Exact-source `just test --locked -p codex-execution-core -p codex-hepta-contracts -p codex-hepta-operations`: **250 passed, 1 skipped**. The ignored destination crash worker is a helper invoked explicitly by its parent tests. See exact-tests.log; all-tests.log and focused-tests.log are earlier checkpoints, not final-source evidence.
- `cargo clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-contracts -p codex-hepta-operations --all-targets -- -D warnings`: passed on identical final tree. Existing unreachable Tokio path warnings from clippy.toml remain; no allow rules added.
- `just fmt --check --base 3d38cc6e786179661d213e815c9b4f0761b2664a` and `git diff HEAD --check`: passed. Python unchanged, not rerun; prior 54-test result belongs to 3d38 source.
- Independent source review passed; diff SHA256 `2a7dae68cea62c0f68281af6a77c29978ef5767c3f19236d90067864499a25a0`. Reviewer did not run Cargo. Suggested explicit SQLx pool closure was incorporated before final qualification.
- Both changed files fetched through GitHub plugin at exact new SHA: nonce test blob `2b0782ba4e4445f811dfe0b2ab249f9a61c7a35c`, durable test blob `c66b150d6e14aec941ffd9fa7d0135ef5c876f53`. Both match local git objects; fetched entire remote tree matches staged/local content. Branch advanced by guarded fast-forward, no merge/deployment.

## Boundaries covered

The actual 40-byte authority.claims format now has a three-record matrix: remove the first/middle/last complete record, duplicate a record, zero/corrupt the tail nonce, partial final frame, and reorder intact frames. Loss/corruption fails with exact InvalidTrust or AntiRollbackViolation on two consecutive opens; failed opens leave disk bytes unchanged. The format is a nonce SET, so intact reorder is valid, but all consumed nonces still return AlreadyClaimed. Trusted-frontier fixtures are in-memory and are explicitly not durable independent custody.

Actual SQLite generation takeover now closes both pools, reopens, rejects an otherwise-current lease with only generation changed, rejects one with only fence changed, and successfully renews the unchanged current lease. Positive control prevents expiration from making the negative cases falsely pass; the original one-second lease was not lengthened. A separate adopted-dispatch test closes/reopens and checks complete row equality plus stale observer StaleGeneration. Its acknowledged-row stale-renew check alone does not isolate generation.

The full run also re-executes existing real cross-process FinalUse lock coverage: live child holds state, parent gets StateLocked; child.kill()/wait(), then reopen still rejects nonce replay. It is not a simultaneous dual-child acquisition stress test. Existing operations crash matrix uses process::exit at controlled boundaries; do not relabel those exits as SIGKILL.

## Commands and environment

Worktree /workspace/pr3567-lock-diagnostic; RUSTUP_HOME=/workspace/rustup, CARGO_HOME=/workspace/cargo, PATH prepended /workspace/cargo/bin, CARGO_TARGET_DIR=/workspace/target-3567, CARGO_BUILD_JOBS=3. Rust/Cargo 1.95.0, just 1.59.0, nextest 0.9.149. Shared cloud allocation 5 CPU, about 17 GiB RAM, no swap; approximately 19 GiB disk free at audit start. Dependencies unchanged; locked Cargo reused the previously validated lock repair. No entire workspace build or model download.

Publication sequence: git fetch origin <exact SHA>; git diff --exit-code <exact SHA>; git reset --soft <exact SHA> only after equality; scoped tests and fmt above; GitHub fetch_file for each changed file; compare git ls-tree HEAD; update_ref with expected old SHA and force=false. Final source worktree clean.

## Pending and limits

At publication, #3582's three runs remain queued. New #3586 HEAD has Python queued (39985936783), blocking pending (39985936749), architecture pending (39985937463), V8 pending (39985937070), no conclusions. Previous HEAD was also queued. No failing job or actionable failure log was available, and no rerun was requested. These are pending hosted execution, not passed gates. Next action is inspect these exact-SHA runs when scheduled and diagnose any actual failure before changes.

No physical power-cut, storage-device flush guarantee, durable independent frontier service, simultaneous multi-process mutation race, same-length live overwrite detection, external downstream hardware/effect acknowledgment, or full-runtime production acceptance was established. This is actual crate integration coverage with explicit test fixtures, not a synthetic receipt validator and not physical acceptance.

Historical repair, original failures, Python checks and initial remote publication evidence remain in ../20261023/README.md at immutable evidence commit a710d7e3f4dd87073d4bc243374b948f99a1f33c.
