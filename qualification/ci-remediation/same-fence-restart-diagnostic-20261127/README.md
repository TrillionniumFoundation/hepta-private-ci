# Preserve the cause of an indeterminate restart

This source candidate starts from commit
`c2326de0631f27aee7178dcdf549f34e73c9b9dc`. It adds failure diagnostics;
it does not repair or qualify the restart operation.

## Observed failure and missing evidence

The retained macOS Intel product test ended after 32.20 seconds with one of
its two original tests passing and the fleet test failing. The two clients
using the same control fence both received errors: `operation_indeterminate`
and `stale_control_fence`. No private mutation error or post-status error was
included in that failure log.

The ordinary daemon handler consumes the next control revision before it
performs the mutation. It then obtains post-status exactly once. Previously,
it discarded both the mutation error and any post-status error while building
the closed RPC response. The stale response therefore does not establish that
the other request succeeded. The retained evidence cannot distinguish a
mutation failure from a post-status failure or identify an underlying driver,
registry, generation, or transport cause.

## Preserved operation and response semantics

The candidate retains the original mutation followed by the original single
post-status call. A mutation error remains the primary failure even when
post-status also fails. Post-status is primary only after a successful
mutation. Both errors are still represented by the original
`operation_indeterminate` response, with the same available `actual` status.
No error detail is added to the RPC schema or client message.

Only the two failure branches for an ordinary `Restart` emit a local
diagnostic. Both explicitly release the supervisor lock after post-status has
been captured and before obtaining the stderr lock or writing. Neither branch
uses the supervisor guard again. Other mutation kinds and signed mutations
gain no diagnostic output, and the successful path retains its existing
response construction. Another request may run while the failed restart's
diagnostic is being written; the captured post-status is not refreshed.

The local record preserves the typed `SupervisorError` debug prefix at the
point where that error was previously discarded. `ProcessDriverError::new`
itself accepts an unbounded string. In the inspected restart-to-drain path,
`runtime::driver_error` applies its existing 512-byte message cap; this is not
a bound on every possible error source. The earlier driver conversion has
already replaced the original typed I/O or JSON error with text. This record
cannot reconstruct an original OS error code, full error chain, or kernel
trace from that text. Local error detail may include filesystem context; the
existing closed wire-error and redaction checks are unchanged.

## Bounded diagnostics

The daemon formats directly into fixed buffers. It never formats a whole
error into an allocated string before truncation. Each of the mutation and
post-status details has a separate 1,536-byte budget and an explicit
`format_complete` flag. The complete attempted record, including both flags,
the fixed stage labels, identity/revision fields, and newline, is at most
4,096 bytes. Incomplete UTF-8 at a buffer boundary is omitted. A large first
error cannot consume the second error's field or its completion flag.

There is one best-effort `Write::write` call, without a flush or retry. Its
result is deliberately not substituted for the original RPC outcome. An I/O
error or short write can leave the diagnostic absent or incomplete. A byte
bound does not bound stderr-lock or write latency; that time remains inside
the existing operation and test budgets.

Only when the original same-fence winner-count assertion fails does its
message read the fixture's existing `supervisord-child.log`. That file already
receives both stdout and stderr from the child daemon. The diagnostic opens
the known fixture path, observes its extent, seeks within the last 8,192 bytes,
and performs one read of at most 8,192 bytes. It does not wait for more output,
retry, or claim that this non-atomic extent is the log's eventual EOF.

The appended diagnostic text is separately capped at 8,192 UTF-8 bytes,
including read metadata and its final completion flag. Lossy decoding and
partial range/format observations are explicit. Log-read failure contributes
only its I/O kind and available code; it cannot replace the original
`left`/`right` failure. The pre-existing error text is not included in this new
diagnostic's byte cap. Other startup-log handling is unchanged.

The locked [`anyhow` 1.0.103 macro source](https://github.com/dtolnay/anyhow/blob/1.0.103/src/ensure.rs)
places formatting arguments inside the failed-condition branch, so the added
log read does not run on a successful winner-count assertion.

## Qualification boundary

All original authority checks, fence comparisons, mutation calls, peer and
release assertions, process cleanup, timeouts, and retries remain in place.
No dependency, lock, workflow, public interface, or protocol schema changes.
The final Agent5 snapshot candidate and the Core completion candidates address
different boundaries and are not evidence that this failure is repaired.

Three added supervisor unit controls cover oversized Unicode causes, primary
failure selection, and a failed diagnostic write. Two small fixture controls
cover a large Unicode log and an unavailable log. They are source additions
only at this checkpoint: no new Rust compilation, unit test, product test, or
native execution has run. The 4 KiB/8 KiB bounds still require those native
controls, and the original same-fence product assertions still require their
normal qualification. No current failure is reclassified as a pass.
