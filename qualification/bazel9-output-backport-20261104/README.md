# Bazel9 native Windows test-output drain

## Observed original failure

On exact Robrix source `767f069c96a6cd2735b3a4166799a1de79017d25`, original Windows job `126326282282` in run `41754188875` returns Bazel exit zero but its 261-byte test log contains only the writer case. The other required case and final Rust summary are absent from the original command stdout and XML too. The strict original two-case reader fails the job. This is retained at [original evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/aa600f9b62ff228fc9cb2301f2bb377673ad2098/qualification/robrix-runfiles-20261104/hosted-767) and [independent ZIP verification](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/347628fd14bacc525371f1084b65aa856563817c/qualification/original-artifact-evidence-20261104/verified-current-20261104). It is not counted as a two-case pass.

## Exact upstream repair

Pinned product Bazel9.0.0 has a native Windows Tee whose background output thread is not joined before its handles are destroyed. Official [Bazel commit e50ebd4](https://github.com/bazelbuild/bazel/commit/e50ebd4a0a0bf5f557aa8d4873d9a226f8e89c57), committed 2026-11-03, fixes this exact output-tail race. The backport applies precisely its three main-source hunks and two added tests to official Bazel9.0.0 source `93f38093f8e24875c1d015e67311853756bdb27e`. Only the insertion context of the tests is re-anchored; every added test line is identical. No other master changes are included.

The official upstream source declares Bazel8.4.2 as its build tool. This is used only to compile the isolated Bazel9.0.0 wrapper source. The product stays on Bazel9.0.0. Fixed original and patched source hashes, patch identity, all 18 original GTest names and both added upstream names are in `source-binding.json`.

## Bounded native verification

The push-only research workflow keeps the original 30-minute native budget. It fetches the exact public upstream commit into a new temporary directory, verifies pristine source, applies the exact patch using actual Git, builds the original `//tools/test:tw` target, and runs the entire original `//tools/test:tw_test` target freshly and unfiltered. A complete independently written native GTest XML must contain all 20 exact cases, zero failure, disabled or skipped cases. Source and lock changes beyond the two pinned files fail the gate.

The helper then copies the complete original Bazel9.0.0 embedded-tools directory and verifies every entry. It replaces only `tools/test/tw.exe` with the just-built native x64 executable. The original installed files remain untouched. Official `--override_repository=bazel_tools=...` selects this complete temporary copy; pinned Bazel's repository lookup explicitly supports that override before resolving its built-in tools.

With that narrowly replaced tool, the unchanged original Robrix qualification script must run both original cases once, retain the complete `2/0/0/0/0` summary and XML, then pass its original Clippy command. The finalizer rechecks every original installed tool and every copied tool after execution, verifies source inputs and the product receipt, and fails if any input or tool changed.

The upstream destructor waits for the pipe to drain, then bounds cancellation for an escaped writer. Those bounds are the exact upstream code. A truncated output still fails the unchanged strict Robrix reader; no success is inferred from exit zero, no test is skipped, and no retry or test-budget increase is added.

## Scope and status

This is an isolated research branch, with no pull request or product-default integration yet. The `.bazelrc` override is confined to this branch and requires its prepared directory. Native execution is pending until the actual hosted workflow finishes. Static hunk application and independent source review are not claimed as C++, GTest or Rust execution.

Posture: **Draft / HOLD_NO_GO / DENY_ALL**. No main merge, deployment, activation or original source deletion.

## First hosted construction failure

Source `58290bcdf0ae2ee7eb12bcd6a8af2627873cd959` fetched and verified the exact upstream source and applied the exact patch, then failed at the builder-version probe before C++ compilation or any test. Bazel8.4.2 rejected the `--version` shortcut placed after startup options. The complete decoded job log and original artifact identity are retained under `first-58290/`. The successor uses the official `version --gnu_format` command after the same startup options, retaining strict version equality. No source patch, build target, test case, assertion, retry count or time budget is changed.

## Second hosted version-reader failure

Source `3616f6fcb1a2fdf77398a3a04bb906301af7b153` reached the actual version command with exit0 but its single-line reader rejected the two correct pinned lines. Independent read-only ZIP verification reconstructed all 29 original stdout bytes: `Bazelisk v1.28.1\nbazel 8.4.2\n`. Pinned Bazelisk's source explicitly prints its own GNU-format version before the underlying Bazel version. The successor requires both exact pinned lines and records the observed versions; it does not discard arbitrary lines or accept other versions. Full negative job output, original stdout/stderr/receipt bytes and the independently executed verification report are retained under `second-3616/`. No C++, GTest or Robrix case had executed on that failed source.
