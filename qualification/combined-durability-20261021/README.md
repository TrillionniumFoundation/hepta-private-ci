# Combined durability and artifact-reader qualification

This receipt covers the integrated Windows memory, state, path-owner and Bao
source at `39a5441b2ef10b9033475e3790ee5ba4f7d082c0`, the exact state literal and
control-pin followup from `a9197efd2a6bf2ea9a8b362afdb6778b528617c9`, and the narrow
artifact-reader change described in `owner-3023-review.json`. The followup is
represented locally by `53b76244e`; it does not change dependency inputs.

## Source and dependency decision

Owner PR #3023 at `a956ba2191e4817cbdeaa4f6a959544b72305c06` adds a final-component
Unix reader check, but its actual Cargo lock omits the new `libc` dependency. This
change consumes only that reader and its regression. It imports `MetadataExt` on
this base, scopes the existing workspace `libc` dependency to Unix, and generates
the missing edge with Cargo. No external package version changes.

The reader opens with `O_NOFOLLOW | O_CLOEXEC`, checks the opened regular file's
size, device, inode, link count and group/other write permissions, and retains the
existing shared lock and bounded read. Ancestor ownership remains the exclusive
writer host's trust boundary. The patch does not repair permissions or truncate
records. A second regression proves that a group-writable record is rejected
without changing bytes or permissions. The positive record fixture uses the
existing private record writer, so it does not depend on the ambient umask.

An independent read-only review by `/root/os_closure` found no blocking defect
within this stated boundary. That source review is separate from the executions
below.

## Actual executions

| Command receipt | Observed result |
| --- | --- |
| `cargo-resolve.json` | Original Cargo resolver, exit 0; one local package dependency edge added. |
| `owner-reader-baseline.json` | New regressions against the old reader: both run and fail at their expected rejection assertions, exit 100. |
| `owner-reader-positive.json` | Original `just test` for learning artifacts: 94 passed; one existing ignored child-worker entrypoint. |
| `bazel-lock-before.json` | Original `just bazel-lock-check`, exit 0. |
| `bazel-lock-update-first.json` | Original `just bazel-lock-update`, exit 0. |
| `bazel-lock-update-second.json` | The same original update repeated, exit 0. |
| `bazel-lock-final-check.json` | Original lock check on the combined source, exit 0. |
| `combined-native.json` | Original `just test` for Bao, Memory, State and path utilities: 528 passed; seven existing ignored qualification probes. |
| `combined-fix.json` | Required scoped `just fix` for the five affected packages, exit 0. Existing nonfatal warnings remain in the raw log. |

The combined native run executed 32 Bao unit tests, three Bao final-use integration
tests, 272 Memory tests, 214 State tests and seven path tests. All seven original
Bao lease-lifecycle assertions ran and passed. `results.json` records their names
and the exact seven ignored Memory probes.

The two Bazel updates and final check preserve identical bytes:

| Lock | Bytes | SHA-256 |
| --- | ---: | --- |
| `codex-rs/Cargo.lock` | 413681 | `4a89de595739e85d8d0e01944914c62217287d2c7daccee8e6d85b1cb4afc941` |
| `MODULE.bazel.lock` | 1745183 | `f6c5dd1f2a09c66d6a4c387ff40d11afb7ed2309e541dcb6bff9ad5f410996c3` |

The real update did not change MODULE lock bytes. No synthesized lock content or
policy exception is used. Each command records its source and lock hashes,
timestamps, exit status, raw-log digest and resource observations. The exact
runner used is archived as `runner.py.raw`; its task-local paths identify the
actual execution environment. Logs are stored as lossless XZ with verified
round trips and SHA-256 digests. The format invocation has its own command
receipt. No tests are run after Clippy fix or formatting.

## Qualification limit

These native runs execute on Linux. They do not execute Windows-only ACL,
retained-directory, recovery or junction regressions. The original hosted
Windows checks remain necessary on the actual published combined head. Current
head and actual base qualification, including the unchanged required aggregate
checks, cannot be inferred from any earlier branch's success.
