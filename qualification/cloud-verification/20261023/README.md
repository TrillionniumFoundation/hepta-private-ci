# Cloud repository verification — PR #3567 → #3582 → #3586

**Source actually checked out and tested:** `3d38cc6e786179661d213e815c9b4f0761b2664a`, tree `aeb4d8fe15af25e09384135a4238c20acaacf7c1`. This evidence-only branch adds records; it does not change that tested product source. No merge or deployment. DRAFT / HOLD_NO_GO for production acceptance.

- [Final source PR #3586](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3586), two commits atop [lock-only PR #3582](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3582).
- Rust repair `0fe8483a848f89a2e02a329bbd4498f4d482d8b1`; mechanical Python formatting and two fixture lambda-to-def rewrites in `3d38cc6…`.
- Exact requested original HEAD `46dc890e40cf5bb7057012e4de756eab73c21351`, parent `97f6383b442be01d48b97596170b4cbac3e23bfc`, then `6a46fba297abf1b641a8637e007595dfd2ad03c8`. Original tree `c3e790d10fea3412f36797a581f8ea1cf200513e`.
- Configured checkout was old `78fdb0cf8537e3a84fc6e0a849707559c80881e8`; none of its tests were attributed to the requested source. Root AGENTS.md read first; initial worktree had no uncommitted changes.

## Completed, exact-source results

[Machine-readable commands and exit codes](exact-results.json) bind every final check to `3d38cc6…`. Checkout was clean before and after all commands.

| Check | Result | Evidence |
|---|---|---|
| `just test --locked -p codex-execution-core -p codex-hepta-contracts -p codex-hepta-operations` | **249 passed, 1 skipped entrypoint** | [Full output](exact-rust-tests.log) |
| `just clippy --locked -p codex-execution-core -p codex-hepta-contracts -- -D warnings` | Exit 0 | [Full output](exact-clippy.log) |
| `just fmt --check --base 2f7ae91c4176896d0b9caf9aea75ed3e030a81f8` | Exit 0 | [Output](exact-fmt.log) |
| Python comparator unittest suite | **54/54 pass** | [Full output](exact-python-tests.log) |
| Frozen Ruff check / format check on all 9 comparator Python files | Both exit 0 | [Lint](exact-ruff-check.log), [format](exact-ruff-format.log) |
| Python compileall / git diff --check | Both exit 0 | [Commands](exact-results.json) |
| Incomplete frozen BASELINE with `[]` evidence | Expected exit **1 / HOLD_NO_GO** | [Rejection](exact-baseline.log) |

The one ignored entrypoint is `destination_recovery_binding::destination_crash_worker`, explicitly invoked by its parent tests with `--ignored --exact`. It is not an omitted independent acceptance scenario or a new skip. All other tests in these three selected packages were run; no full workspace, Windows/macOS, all-features or full Bazel test suite was run. Clippy was scoped to the two changed Rust packages, not every transitive crate. Three existing clippy.toml unreachable-Tokio-type configuration warnings remain in its successful command output; no `allow` or lint downgrade was added.

## What was reproduced and repaired

1. Original `46dc890…` passed 54 Python tests but locked Rust commands failed before target compilation. `execution-core` had the sole ambiguous unversioned `sha2` dependency reference while Cargo.lock contained two sha2 versions. Lock-only `2f7ae91…` selects `sha2 0.10.9`, matching the workspace manifest. [Original lock failure](original-rust-check.log), [lock patch](original-lock-disambiguation.patch), [lock review/remote proof](LOCK-REVIEW.md).
2. With that lock repaired, 191 original Rust tests ran: 190 passed, one failed. The existing downgrade fixture expected AuthorizationDenied but actually reached the earlier Binding rejection. [Original failure](original-patched-rust-tests.log). The follow-up asserts the correct exact downgrade error and unchanged journal, retains exact stale-start denial, and adds a genuine absent-grant case whose host verifier panics if called. No production execution-journal authorization was relaxed.
3. Previously unattached nonce tests described an obsolete 80-byte `authority.nonces` format. The real product path uses 40-byte `authority.claims` frames. A migrated public-API regression **failed on the old store**: after a live journal was truncated, another claim incorrectly returned `Ok(VerifiedUseToken)`. [Before](nonce-before.log).
4. Store now remembers validated journal byte length, checks it before append, and updates only after successful sync. The existing error path fences the owner. Nine correctly attached regressions pass: live truncation at 0/39, growth to 41/80, missing log, fixed-width claims/reopen, strict torn-tail rejection, malformed frames, trusted-frontier corruption detection, and revocation/epoch snapshot crash cuts including old-epoch residual bytes followed by a new valid claim. [After](nonce-after.log), [all 13 original test properties mapped](NONCE-MIGRATION.md).
5. Four original scoped Clippy findings were repaired without waivers. Connecting a new test helper exposed seven unwrap lint failures, which were retained and repaired using Result/? plus exact error assertions. [Original Clippy](original-patched-clippy.log), [intermediate helper failure](clippy-new-helper-failure.log).
6. Original direct Ruff found two inherited E731 findings and nine files needing formatting; the repository formatter did not cover qualification/. The two local fixture functions now use def; formatting of nine files is mechanical. Independent AST normalization confirmed no other semantic differences. [Original lint](original-ruff-check-retry.log), [original format](original-ruff-format-retry.log), [independent AST proof](independent-python-ast.json).

## Independent review and remote verification

[Independent review](independent-review.md) found no blocking defect in the 16-file source diff. It is bound to diff SHA-256 `65699b27aa19d0c4e302a40da1ace657d47e3b6bca15e460afedd7ea2587e8db` and [per-file reviewed hashes](independent-review-source-manifest.json). Reviewer did not falsely claim to have run the primary agent's Cargo commands; final executed source results are separately recorded above.

All 16 source files were read back through the GitHub plugin at exact `3d38cc6…`; each returned blob SHA equals the local hash. [Per-file proof](remote-files.json). Independently constructed local Rust tree `33283af6848ca1dc732694db611db005f449f3c7` and full tree `aeb4d8fe15af25e09384135a4238c20acaacf7c1` match GitHub tree objects. Git-fetch plus complete tracked-tree diff was empty before adopting the exact commit and executing final checks. No original/default branch was mutated.

## Real recovery coverage and limits

- `final_use::tests::killed_owner_releases_lock_but_keeps_claim` really calls child.kill, waits, reopens the actual authority store and rejects nonce replay.
- `hepta-operations::fault_tests::child_process_kill_matrix_preserves_durable_effect_semantics` is a real subprocess/store test, but its crash cuts use **process::exit(81/82/83)**, not SIGKILL. The parent checks prepared/during-effect/after-ack states. A local marker proves fixture callback entry, not an independent physical outcome.
- `destination_recovery_binding` exercises the product DestinationDedupeStore transaction with a real SQLite domain counter plus dedupe record. Children use **process::exit(73/74)** before/after commit, without Rust destructors. Recovery checks rollback or no repeated domain mutation. Its child.kill is only the failure watchdog.
- The earlier 17-test durable-store subset used close/reopen and explicit lease expiry; final 249-test run additionally includes the real subprocess and destination transaction tests. These distinctions must not be collapsed into “all crash/power-loss tested.”
- ExecutionJournal remains a volatile, non-executing control protocol. The Python comparator does not invoke Rust physical execution. Local store recovery does not establish deployed Agentd integration, target hardware, production signer custody, independent observation or power-loss durability.
- Length fencing does **not** detect same-length overwrite/replacement or hostile concurrent mutation after the check. Strong antirollback still depends on the independent trusted frontier; legacy no-frontier constructors are not promoted to that guarantee.

## Two practical durable-execution approaches

[Temporal's official Activity contract](https://docs.temporal.io/activity-definition) requires activities to be designed for idempotence; retries need stable effect identity and receiver dedupe or reconciliation. [DBOS's workflow documentation](https://docs.dbos.dev/python/tutorials/workflow-tutorial) distinguishes transactional commit from retryable steps. A transaction can jointly commit the local domain mutation and dedupe row, but cannot atomically cover an arbitrary external device/API effect.

The selected repository tests apply both boundaries: DestinationDedupeStore verifies domain+dedupe transaction recovery; DurableOperationStore preserves unknown effects as Indeterminate pending observation; FinalUse verifies consumed authority cannot be replayed after owner death. This reuses product implementations rather than duplicating the dot team's two-store mechanism experiment or constructing another synthetic receipt validator.

## Environment, dependencies and remaining gates

Linux x86_64, 5 CPUs, ~17 GiB memory, no swap; ~30 GiB free initially. Installed into writable workspace without changing shell profiles or security settings: Rust/Cargo 1.95.0, rustfmt/clippy/rust-src, Just 1.59.0, nextest 0.9.149, Bazel 9.0.0. Python 3.12.14. Cargo builds/tests retained `--locked`; Ruff used `scripts/uv.lock` through `uv run --frozen`. Product dependency identity is the exact source [Cargo.lock](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3d38cc6e786179661d213e815c9b4f0761b2664a/codex-rs/Cargo.lock), not the build tools' own dependencies.

Git network and Rust distribution access worked. Default UV/Bazel cache directories were read-only; caches were redirected into the workspace. Bazel's crashed stale server was avoided using a new batch output root; successful lock update changed no MODULE.bazel.lock bytes. [Bazel output](original-bazel-lock-update-batch.log), [initial complete commands](original-COMMANDS.txt), [original source manifest](original-source-manifest.json), [final command details](exact-results.json).

Hosted CI at final source must complete independently; queued checks are not passes. Full workspace/platform/Bazel tests and real production physical acceptance remain open. No new models downloaded, no duplicate cloud task, no production credentials generated, no merge, no deployment, no security setting change and no gate relaxation. See PR #3586 for live exact-head CI status rather than treating this immutable record as a future status feed.
