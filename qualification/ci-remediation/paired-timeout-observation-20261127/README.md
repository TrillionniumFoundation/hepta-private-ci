# Retain paired product test phases on timeout

## Observed gap

The original c232 Intel target timed out after 300.4 seconds. Both product test
names exceeded 60 seconds, but both acquire the same process-wide mutex before
fixture work. That output cannot establish two independent lifecycle hangs or
identify the test that held the mutex. The existing five-pair `eprintln!` phase
messages did not appear in the retained nonterminal test log.

The repository pins Rust 1.96.0. Its standard library routes `_eprint` through
`print_to_buffer_if_capture_used`, while `Write::write_all` on a `Stderr` handle
delegates to the locked raw stream. The inspected upstream source is
[`library/std/src/io/stdio.rs`](https://github.com/rust-lang/rust/blob/1.96.0/library/std/src/io/stdio.rs),
Git blob `2d80fe49e80a7ddb7a01792caf96f121527b7a52`, SHA-256
`83a4386e70e8d7127213c24854ffb985beac0efac8b8617275db0cc16babe040`.

## Change

Write fixed byte-string markers directly through the stderr handle before and
after lock acquisition and the existing construction, warm-up, start, recovery,
restart, replacement, and shutdown boundaries. Replace the five captured elapsed
messages with static stage names. There are no markers inside polling loops or
child request loops. No path, identifier, request, configuration, or model data
is logged.

The diagnostic write result is ignored so a write error does not replace the
original test result. The output is bounded by a finite number of static call
sites. This bounds bytes, not stderr lock acquisition or operating-system write
latency. The target's existing timeout still owns termination.

The shared test mutex, its poison behavior, child execution, all lifecycle
operations and ordering, deadlines, polling intervals, restart budgets, and
success assertions stay unchanged. The helper changes only this integration
test binary. There is no production, workflow, dependency, permission, or test
selection change.

## Interpretation and qualification

`lock_wait` without the matching `lock_acquired` identifies a waiting test, not
its peer's internal cause. A begin marker without a completion marker means that
boundary did not report successful completion; it can also precede a returned
error or panic. `body_complete` precedes ordinary Rust local destruction and is
not a process-exit or mutex-release acknowledgement. Missing markers can still
reflect a failing or blocked output sink.

Source inverse checks verify that removing only these diagnostics restores the
original test and fixture code. Static preparation is not a native test pass.
The original timeout remains open until normal CI supplies actual target output
and a terminal result. No timeout, retry, privilege, or assertion was relaxed to
obtain evidence, and no old native test or model experiment was replayed.
