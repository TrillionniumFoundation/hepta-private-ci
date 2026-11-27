# CLI resume timeout: process exit observation

## Original evidence and remaining gap

The retained Windows `core-all-test/shard_1_of_16/test_attempts/attempt_1.log`
at source `0a64b1b2be83d2b6724899cb66c1e63b94ede6ac` records the second
`run_cli_command` in `integration_creates_and_checks_session_file` returning
`TimedOut` at the original line 614. The first CLI call and its rollout-content
assertions have already completed. The log does not contain the second child's
output, exit status, or request count. Its 74.41-second summary covers the whole
60-test binary attempt, not this call. This is separate from the other Windows
failures that report an unsupported sandbox backend.

The original helper moves `Child` and both output pipes into a detached waiter,
then waits up to 30 seconds for `wait_with_output`. Rust 1.96 collects both pipes
before its final process wait. Therefore this error alone does not distinguish
a process still running from one that exited before output collection or waiter
delivery finished. The source also leaves the waiter unjoined on timeout and
uses the existing PID-based cleanup guard; neither fact proves this failure's
cause.

## Fixed observation contract

Only the second resume command opts in. The first command and every other call
retain the default unobserved route. Non-Windows builds use the same original
collector without this observation. All command arguments, environment choices,
mock responses, session assertions, timeouts, and cleanup operations remain.

Before moving `Child` into the unchanged waiter, the Windows path attempts to
duplicate its existing process handle into an `OwnedHandle`. Rust's pinned
`BorrowedHandle::try_clone_to_owned` uses `DUPLICATE_SAME_ACCESS` with inheritance
disabled. No PID is opened, no new access is requested, and no token, ACL, job,
or process action is added. Failure to duplicate is retained as an unknown
observation and does not prevent the original command from running. The new
observer is declared before the original cleanup guard, so its duplicate remains
valid through that guard's unchanged cleanup. The owned duplicate is then closed
by RAII. Retaining the process object does not keep the process executing.

Only after the original `recv_timeout(CLI_TIMEOUT)` returns `Timeout` does the
observer call `WaitForSingleObject` once with a zero timeout. A nonsignaled result
is recorded as running at that instant. A signaled result permits one
`GetExitCodeProcess` call; successful exit code 259 is an exit code, not a liveness
test. API failure captures the immediate OS error. Any unexpected wait result
is an error, never a successful observation. There is no wait loop, retry,
additional child, kill, job operation, or attempt to recover a late output as
success.

The diagnostic contains only a fixed case label, clone/query status, process
state, optional numeric exit/OS error, error-kind name, and local observation
duration. Formatting writes directly into a 1,024-byte array. Formatting failure
selects a fixed unknown record. One best-effort stderr write can be short or
fail; neither outcome replaces the original `TimedOut` kind or message. Byte
bounds do not bound stderr I/O latency. The original 30-second receive interval
is unchanged, while setup and failure reporting still contribute to total call
duration outside that interval.

The deadline, zero-timeout wait, exit-code query, and waiter progress are not an
atomic snapshot. An exited observation does not prove the child had exited at
the deadline. A running observation may already be stale when logged. Neither
result identifies a stuck pipe, thread, shutdown phase, or kernel cause. A
missing or partial record remains unknown.

## Source and qualification boundaries

The narrow interface lives in `codex-utils-pty`, which Core already directly
depends on. Its existing Windows dependency is `winapi` 0.3.9, with the required
`synchapi`, `processthreadsapi`, `winbase`, and `winerror` features already enabled.
This change does not use `WinChild::is_complete`, whose completion path also
preserves descendants. No dependency, feature, lockfile, workflow, retry, or
job-budget change is needed. The existing Bazel source globs cover both new Rust
modules.

This candidate has source and static validation only. No Rust compilation,
new child execution, process-query test, or native CI run has occurred. Running,
exited, API-error, clone-error, exit-259, and stderr-failure behavior have not been
qualified by a new native experiment. A future ordinary CI pass that does not
enter this timeout arm would not prove that the observation executed. Existing
Windows functional failures and the original timeout remain open.

## Authored Windows controls, not yet executed

Two sibling unit tests cover the public observer independently of the CLI's
timeout branch. They reuse the existing `COMSPEC`/`cmd.exe` selection and `SET /P`
stdin gate. Each creates one owned `Child`, holds its stdin pipe without input,
and captures both `Child::try_wait` and the observer before closing the pipe.
The first expects no exit yet and `Running`, then an explicit exit code 0. After
dropping the original `Child`, its duplicate must still report `Exited(0)`. The
second applies the same lifecycle with explicit exit code 259 and requires
`Exited(259)`. The command explicitly overrides `SET /P`'s EOF errorlevel. There
are no readiness sleeps, output pipes, or detached waiter threads in these
controls.

These test-only controls keep the original child handle for cleanup. Normal
completion has a five-second deadline, using a finite wait followed by
`Child::try_wait`. On failure only, one standard `Child::kill` is attempted and a
second finite wait uses the remaining part of the same total ten-second
deadline. No PID is opened, and no job or production cleanup is changed. Every
assertion and post-spawn error propagation occurs after input release, normal
completion or failed-control cleanup, and dropping the original `Child`.
Failure remains failure even if cleanup later succeeds; cleanup error kinds and
numeric OS codes are attached to the retained control error. If termination or
reaping fails, the test cannot claim the child is gone. The wait deadlines do
not impose hard latency bounds on spawn, kill, handle closure, or OS scheduling.

The two tests are authored only: zero new child processes or tests have run.
They do not change the zero-timeout production observer, the original CLI
30-second receive deadline, any existing test, or any job budget. They do not
qualify clone-error, API-error, or stderr-failure branches, and they do not repair
the original resume timeout or the unsupported Windows execution backend.
