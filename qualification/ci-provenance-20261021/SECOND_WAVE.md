# Hidden index state and optional Bazel binary lookup

Observed on 2026-10-21 UTC. This update follows PR #2968 commit
`f740aaef183e0c1724871189fe1d72fc5204a49d`.

## Git receipt integrity

Real Git repositories demonstrated that `assume-unchanged`, `skip-worktree`,
and a stale fsmonitor response can hide modified tracked input from ordinary
`git status`. Replacement-ref protection alone did not cover these cases.

Receipt probes now disable fsmonitor and optional index refresh writes. A
repository-root, NUL-delimited `ls-files -v` inspection rejects hidden index
flags before dispatch and after command completion. It does not clear flags,
invoke the configured monitor hook, or rewrite the index. The receipt schema
is unchanged; unqualified index state is reported through the existing dirty
identity field.

This deliberately rejects a legitimate sparse checkout with skip-worktree
flags. Qualification must use a complete worktree with no hidden index flags.
These checks are not a hermetic execution boundary against arbitrary Git
configuration, wrappers, filters, concurrent edits, or command behavior.

Five new test methods produced ten failing assertions against the exact f740
executor. The fixed combined executor/deadline/output suite passed **54/54**
tests with zero skips in the author, independent reviewer, and root runs.
Controls include clean and changed flagged files, a nested caller, a filename
containing a newline, mutation after dispatch, and clean/stale fsmonitor
responses. The positive cases also check unchanged index bytes.

## Optional Bazel binary lookup

Windows Bazel jobs `118912168129` and `118912241314` on parent #2944 reached
`assert_cmd` 2.2.2's panic path when an optional binary had no declared
`CARGO_BIN_EXE_*` entry. Callers using `.ok()` or `if let Ok` could not handle
that panic as a missing optional binary.

`codex-utils-cargo-bin` now returns its existing `NotFound` error when a
manifest-only Bazel test has no matching declared binary. Declared paths still
pass through the existing runfiles resolver, including its invalid-path
errors. Ordinary Cargo sibling-binary fallback remains available. No binary
dependencies, lockfiles, lint settings, or skipped-test rules are changed.
The existing Bazel macro includes the new `tests/manifest_only.rs` through its
`tests/*.rs` integration-test glob.

A Linux Rust harness using the exact helper and pinned production dependencies
reproduced both original panic cases: **2/2 failed before**, **2/2 passed after**,
zero skips. It used the repository's `just test` and nextest entry points.
Seven additional actual manifest/path/process probes passed, including both
binary-name aliases, changed working directory, missing mappings/targets,
forbidden Bazel sibling fallback, and preserved Cargo execution. Scoped strict
Clippy and `just fmt` passed. This harness has an isolated dependency closure;
it is not the full locked production workspace or native Windows/Bazel job.

## Outstanding qualification

The complete platform matrix and dependency gate remain independent gates.
On f740, cargo-deny job `118974143841` failed in its `Run cargo-deny` step;
policy enforcement and clean-worktree checks passed. The log connector could
not retrieve its output, so its detailed cause is still under investigation.
Do not turn earlier, skipped, pending, or narrowly scoped successes into
passing results for the next pushed commit. Research remains
`SHADOW_ONLY / DENY_ALL / NO_GO`.
