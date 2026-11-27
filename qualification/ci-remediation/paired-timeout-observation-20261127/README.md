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

## Initial phase observation

The initial change wrote fixed byte-string markers through the stderr handle before and
after lock acquisition and the existing construction, warm-up, start, recovery,
restart, replacement, and shutdown boundaries. It replaced the five captured elapsed
messages with static stage names. These stage calls are outside polling loops and
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

## b63 readiness observation

The complete b63 Intel test log records a passing two-pair test. The five-pair
test created its fixture, completed its single-pair warm-up, and completed
`start_all`. Its last marker is `five_pairs ready_wait_begin`. The actual
TestRunner returned `TIMEOUT` / exit 142 after 300.252 seconds; the later XML
writer's zero exit is not a passing test. The source input for this fixture
matches b63 exactly. Console timestamps were assigned when the completed log
was printed and cannot measure the stages. The libtest 60-second notices also
include time spent waiting for the shared fixture mutex.

Keep all 45 existing stage labels and call sites in order, adding `elapsed_ms`
from one process-local monotonic origin initialized by the first marker. This
origin includes later mutex waiting; it is neither process start nor CPU time.
Each stage is formatted into a 128-byte stack buffer and passed to one
best-effort stderr `write_all` call. The longest existing label with a full
decimal `u128` elapsed value and newline is 103 bytes.

Only `wait_agents_ready` gains two failure observations. A nonempty tick fault
list emits the fixed cause `tick_fault` immediately before the original
`ensure!`. The existing deadline branch emits `deadline_reached` before its
original snapshot collection and `bail!`. Each record contains only the fixed
cause, elapsed milliseconds, selected-agent count, and already available fault
count. There is no successful-poll logging, additional snapshot, error body,
path, identifier, PID, child output, or health-probe payload. The original
error text, readiness predicate, and result propagation remain unchanged.

Failure records use a 256-byte stack buffer. With full `u128` elapsed and
64-bit `usize` counts, the longest record is 149 bytes; even 128-bit counts
would fit in 187 bytes. There are four readiness-helper invocations across
one execution of the two product tests, with at most one failure record per
invocation. Counting all 45 stage sites and four possible failure records
conservatively caps their buffers' total output at 6,784 bytes including
newlines. The actual fixed formats on 64-bit targets have a tighter total
bound of 4,768 bytes. Early failures reduce the reachable output.

The original 300-second target budget, 60-second readiness and health budgets,
10-second warm-up stop wait, 5-second shutdown wait, polling intervals, fixture
lock, child behavior, and every assertion remain unchanged. The readiness
deadline is checked after synchronous `tick`; it cannot interrupt that call.
These observations do not expose health-probe errors, establish a particular
blocking instruction, or distinguish CPU time from scheduling or I/O waits.
An error marker also does not acknowledge completed local destruction or
delivery of the final libtest result. Clock initialization, formatting, and
stderr writes add overhead; bounded bytes do not bound their latency.

Whole-file inverse checks remove only this observation increment and recover
the exact b63 fixture. Formatting and source checks do not execute the Rust
test or establish a timeout fix. Native qualification remains pending a
separately authorized normal CI update; no deadline or assertion is relaxed.
