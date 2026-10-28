# Windows 832: path fixture, restart recovery, and matrixd owner control

This patch contains six Rust files. It is ready for source review; compilation and
execution remain CI gates. No dependency, lockfile, Bazel target, test skip flag,
owner identity check, restart limit, or durable journal format changed.

## Evidence

The two adjacent log files preserve the relevant failure excerpts verbatim from
workflow 40661665726. They are not complete job logs. Job 122730593496 reported
79 memory-extension tests passing, one failing, and 22 filtered in that group;
the restart recovery target reported zero passing and one failing. Job
122730593641 reported 30 matrixd tests passing and one failing.

## Memory extension

The invalid-path test constructed `canonical.join("..")`. Windows canonical
paths have a verbatim prefix; Rust normalizes parent steps during that join.
The test therefore sent a valid parent directory (`\\?\D:\tmp`) to the guard.
The fixture now appends the literal separator and parent step through OsString,
so the existing production rejection actually receives a ParentDir component.
Relative, missing, ordinary-file, transported valid-path, and Unix symlink cases
remain. Production registration and grant identity code are unchanged.

Primary API reference: https://doc.rust-lang.org/std/path/struct.PathBuf.html#method.push

## Supervisor

The authoritative journal already rejected a fourth automatic restart. Recovery
only restored the in-memory attempt counter when a restart was pending. A
completed replacement has pending=false but still consumes its persisted
attempts, so the recovered slot incorrectly reported zero attempts in the
exhaustion event.

The restart-budget port now returns attempts and an optional pending claim from
one validated canonical read. Recovery installs the count for both completed and
pending cases. The public pending_restart API remains compatible. Existing
backoff, expiry, durable validation, completion, cap, and owner fences remain.
The existing full recovery integration test now additionally checks the active,
completed snapshots at attempts 1, 2, and 3 before the next crash. Its original
exact exhaustion event, TickReport, and four-total-spawns assertions remain.

## Matrixd

The earlier stale-path error is not evidence that Windows can authenticate an
owner-local peer. The existing codex_uds Windows implementation unconditionally
returns Unsupported from ensure_current_user_peer. An owner-authenticated
matrixd control server therefore cannot serve a valid request on that backend.

The non-Unix bind method now refuses with Unsupported before directory creation,
connect, stale-path cleanup, socket binding, or permission changes. The Unix bind
and per-connection peer check remain unchanged. This is an explicit unsupported
contract; it does not implement Windows owner authentication or general UDS path
normalization.

The former complete Unix socket positive is preserved in a new platform test
file. A separate test exercises the actual state response and health transitions
on all platforms. A non-Unix test calls the real bind method for a missing parent
and an existing rendezvous file, requiring exact Unsupported and unchanged path
existence, directory entries, file bytes, and file read-only attributes. The
parent-directory assertion is limited to these bind calls, not all matrixd
startup or durable-store setup.

The new platform module declares two executable tests per current platform:
health plus Unix owner UDS, or health plus non-Unix refusal. Other tests and the
Bazel target remain enabled. Relative to the observed 31 Windows matrixd tests,
this should yield 32, subject to the actual next CI enumeration. No zero-test
platform target was introduced.

The small cfg-specific replacement stays beside the existing bind method;
new test functionality lives in the separate file, reusing four existing
private test fixtures instead of copying durable-store setup.

## Validation and limits

All three requested just test commands and all three scoped just fix commands
returned 101 before compilation because this sparse checkout is missing
codex-rs/aws-auth/Cargo.toml. Full logs and commands are in VALIDATION.json.
The repository formatter's scoped_formatter_groups/run_formatter_group path
formatted only these six files successfully. Git diff whitespace checks passed.
No Rust test or Windows execution success is claimed. The next CI must compile
and run the strengthened recovery, registration, and platform-contract tests.
